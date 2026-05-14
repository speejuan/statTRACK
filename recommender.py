import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from scipy.sparse.linalg import svds
from scipy.sparse import csr_matrix


class ContentBasedRecommender:
    def __init__(self, movies_df, tags_df=None):
        self.movies = movies_df.copy().reset_index(drop=True)
        self._build_features(tags_df)

    def _build_features(self, tags_df):
        self.movies["genre_str"] = self.movies["genres"].str.replace("|", " ", regex=False)

        if tags_df is not None:
            movie_tags = (
                tags_df.groupby("movieId")["tag"]
                .apply(lambda x: " ".join(x.astype(str).str.lower()))
                .reset_index()
            )
            self.movies = self.movies.merge(movie_tags, on="movieId", how="left")
            self.movies["tag"] = self.movies["tag"].fillna("")
            self.movies["features"] = self.movies["genre_str"] + " " + self.movies["tag"]
        else:
            self.movies["features"] = self.movies["genre_str"]

        tfidf = TfidfVectorizer(stop_words="english")
        tfidf_matrix = tfidf.fit_transform(self.movies["features"])
        self.sim_matrix = cosine_similarity(tfidf_matrix)

        # Map exact title -> integer row index (drop duplicates, keep first)
        self.title_to_idx = (
            pd.Series(self.movies.index, index=self.movies["title"])
            .groupby(level=0)
            .first()
        )

    def get_similar_movies(self, title, n=10):
        if title not in self.title_to_idx:
            return pd.DataFrame()
        idx = self.title_to_idx[title]
        sim_scores = list(enumerate(self.sim_matrix[idx]))
        sim_scores = sorted(sim_scores, key=lambda x: x[1], reverse=True)[1 : n + 1]
        rows = [s[0] for s in sim_scores]
        scores = [s[1] for s in sim_scores]
        result = self.movies.iloc[rows][["movieId", "title", "genres"]].copy()
        result["score"] = scores
        return result.reset_index(drop=True)


class CollaborativeFilteringRecommender:
    def __init__(self, ratings_df, movies_df, n_factors=50):
        self.movies = movies_df
        self._build_model(ratings_df, n_factors)

    def _build_model(self, ratings_df, n_factors):
        self.ratings_matrix = ratings_df.pivot(
            index="userId", columns="movieId", values="rating"
        ).fillna(0)

        user_mean = self.ratings_matrix.mean(axis=1)
        R_demeaned = self.ratings_matrix.subtract(user_mean, axis=0)

        k = min(n_factors, min(R_demeaned.shape) - 1)
        U, sigma, Vt = svds(csr_matrix(R_demeaned.values), k=k)
        predicted = np.dot(np.dot(U, np.diag(sigma)), Vt) + user_mean.values.reshape(-1, 1)
        self.predicted_df = pd.DataFrame(
            predicted,
            index=self.ratings_matrix.index,
            columns=self.ratings_matrix.columns,
        )

        # Item-item cosine similarity on the ratings space
        item_matrix = self.ratings_matrix.T.values
        item_sim = cosine_similarity(item_matrix)
        self.item_sim_df = pd.DataFrame(
            item_sim,
            index=self.ratings_matrix.columns,
            columns=self.ratings_matrix.columns,
        )

    def recommend_for_user(self, user_id, n=10, already_rated=None):
        if user_id not in self.predicted_df.index:
            return pd.DataFrame()
        preds = self.predicted_df.loc[user_id].copy()
        if already_rated:
            preds = preds[~preds.index.isin(already_rated)]
        top = preds.nlargest(n)
        result = self.movies[self.movies["movieId"].isin(top.index)].copy()
        result["score"] = result["movieId"].map(top.to_dict())
        return result.sort_values("score", ascending=False).reset_index(drop=True)

    def get_similar_movies(self, movie_id, n=10):
        if movie_id not in self.item_sim_df.index:
            return pd.DataFrame()
        sims = self.item_sim_df[movie_id].drop(index=movie_id, errors="ignore")
        top = sims.nlargest(n)
        result = self.movies[self.movies["movieId"].isin(top.index)].copy()
        result["score"] = result["movieId"].map(top.to_dict())
        return result.sort_values("score", ascending=False).reset_index(drop=True)


class HybridRecommender:
    def __init__(self, cb, cf, movies_df, ratings_df):
        self.cb = cb
        self.cf = cf
        self.movies = movies_df
        self.ratings = ratings_df

    def _normalize(self, series):
        lo, hi = series.min(), series.max()
        return (series - lo) / (hi - lo + 1e-9)

    def recommend(self, user_id=None, movie_title=None, n=10, cb_weight=0.4, cf_weight=0.6):
        scores = {}
        already_rated = set()

        if user_id is not None:
            already_rated = set(
                self.ratings[self.ratings["userId"] == user_id]["movieId"].tolist()
            )

        if movie_title:
            cb_recs = self.cb.get_similar_movies(movie_title, n=n * 3)
            if not cb_recs.empty:
                normed = self._normalize(cb_recs["score"])
                for mid, s in zip(cb_recs["movieId"], normed):
                    scores[mid] = scores.get(mid, 0) + cb_weight * s

            movie_row = self.movies[self.movies["title"] == movie_title]
            if not movie_row.empty:
                mid_input = movie_row.iloc[0]["movieId"]
                scores.pop(mid_input, None)
                cf_item = self.cf.get_similar_movies(mid_input, n=n * 3)
                if not cf_item.empty:
                    normed = self._normalize(cf_item["score"])
                    for mid, s in zip(cf_item["movieId"], normed):
                        if mid != mid_input:
                            scores[mid] = scores.get(mid, 0) + (1 - cb_weight) * s

        if user_id is not None:
            cf_user = self.cf.recommend_for_user(user_id, n=n * 3, already_rated=already_rated)
            if not cf_user.empty:
                normed = self._normalize(cf_user["score"])
                for mid, s in zip(cf_user["movieId"], normed):
                    scores[mid] = scores.get(mid, 0) + cf_weight * s

        scores = {mid: s for mid, s in scores.items() if mid not in already_rated}

        if not scores:
            return pd.DataFrame()

        top_ids = sorted(scores, key=scores.get, reverse=True)[:n]
        result = self.movies[self.movies["movieId"].isin(top_ids)].copy()
        result["score"] = result["movieId"].map(scores)
        return result.sort_values("score", ascending=False).reset_index(drop=True)

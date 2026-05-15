import os
import json
import time
import threading
import concurrent.futures
import urllib.request
import urllib.parse
import urllib.error

import pandas as pd
from flask import Flask, jsonify, redirect, render_template, request, url_for

from database import (
    init_db,
    library_add,
    library_all,
    library_delete,
    library_update,
    watchlist_add,
    watchlist_all,
    watchlist_delete,
    watchlist_move,
)
from recommender import (
    CollaborativeFilteringRecommender,
    ContentBasedRecommender,
    HybridRecommender,
)

app = Flask(__name__)
init_db()

# ── TMDB config ───────────────────────────────────────────────────────────────

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


def get_tmdb_key():
    key = os.environ.get("TMDB_API_KEY", "")
    if not key and os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                key = json.load(f).get("tmdb_api_key", "")
        except Exception:
            pass
    return key.strip()


# ── Lazy-loaded recommender globals ─────────────────────────────────────────
_rec = None          # HybridRecommender
_movies = None       # movies DataFrame
_rec_lock = threading.Lock()

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def _load_recommenders():
    global _rec, _movies
    if _rec is not None:
        return
    with _rec_lock:
        if _rec is not None:
            return
        movies = pd.read_csv(os.path.join(DATA_DIR, "movies.csv"))
        ratings = pd.read_csv(os.path.join(DATA_DIR, "ratings.csv"))
        tags_path = os.path.join(DATA_DIR, "tags.csv")
        tags = pd.read_csv(tags_path) if os.path.exists(tags_path) else None

        cb = ContentBasedRecommender(movies, tags)
        cf = CollaborativeFilteringRecommender(ratings, movies)
        hybrid = HybridRecommender(cb, cf, movies, ratings)

        _movies = movies
        _rec = hybrid


def _resolve_title(query):
    if query in _movies["title"].values:
        return query
    matches = _movies[_movies["title"].str.contains(query, case=False, na=False)]
    if matches.empty:
        return None
    return matches.iloc[0]["title"]


# ── Page routes ───────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return redirect(url_for("library"))


@app.route("/library")
def library():
    type_ = request.args.get("type", "")
    status = request.args.get("status", "")
    items = library_all(type_=type_ or None, status=status or None)

    counts = {"movie": 0, "book": 0, "manga": 0, "anime": 0, "show": 0}
    for item in library_all():
        t = item.get("type")
        if t in counts:
            counts[t] += 1

    return render_template(
        "library.html",
        items=items,
        counts=counts,
        active_tab="library",
        filter_type=type_,
        filter_status=status,
    )


@app.route("/watchlist")
def watchlist():
    type_ = request.args.get("type", "")
    items = watchlist_all(type_=type_ or None)
    return render_template(
        "watchlist.html",
        items=items,
        active_tab="watchlist",
        filter_type=type_,
    )


@app.route("/discover")
def discover():
    return render_template("discover.html", active_tab="discover")


# ── Library API ───────────────────────────────────────────────────────────────

@app.route("/api/library", methods=["POST"])
def api_library_add():
    data = request.get_json(force=True)
    title = (data.get("title") or "").strip()
    type_ = data.get("type", "movie")
    status = data.get("status", "plan_to_watch")
    rating = data.get("rating")
    notes = (data.get("notes") or "").strip() or None
    cover_url = (data.get("cover_url") or "").strip() or None
    if not title:
        return jsonify({"error": "title required"}), 400
    try:
        rating = float(rating) if rating not in (None, "", "null") else None
    except (ValueError, TypeError):
        rating = None
    new_id = library_add(title, type_, status, rating, notes, cover_url)
    return jsonify({"id": new_id}), 201


@app.route("/api/library/<int:id>", methods=["PATCH"])
def api_library_update(id):
    data = request.get_json(force=True)
    kw = {}
    for field in ("status", "notes", "date_completed", "cover_url"):
        if field in data:
            kw[field] = data[field]
    if "rating" in data:
        try:
            kw["rating"] = float(data["rating"]) if data["rating"] not in (None, "", "null") else None
        except (ValueError, TypeError):
            kw["rating"] = None
    library_update(id, **kw)
    return jsonify({"ok": True})


@app.route("/api/library/<int:id>", methods=["DELETE"])
def api_library_delete(id):
    library_delete(id)
    return jsonify({"ok": True})


# ── Watchlist API ─────────────────────────────────────────────────────────────

@app.route("/api/watchlist", methods=["POST"])
def api_watchlist_add():
    data = request.get_json(force=True)
    title = (data.get("title") or "").strip()
    type_ = data.get("type", "movie")
    notes = (data.get("notes") or "").strip() or None
    cover_url = (data.get("cover_url") or "").strip() or None
    if not title:
        return jsonify({"error": "title required"}), 400
    new_id = watchlist_add(title, type_, notes, cover_url)
    return jsonify({"id": new_id}), 201


@app.route("/api/watchlist/<int:id>", methods=["DELETE"])
def api_watchlist_delete(id):
    deleted = watchlist_delete(id)
    return jsonify({"ok": True, "deleted": deleted})


@app.route("/api/watchlist/<int:id>/move", methods=["POST"])
def api_watchlist_move(id):
    data = request.get_json(force=True)
    status = data.get("status", "plan_to_watch")
    new_id = watchlist_move(id, status=status)
    if new_id is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True, "library_id": new_id})


# ── TMDB / Sidebar API ────────────────────────────────────────────────────────

@app.route("/api/config/tmdb", methods=["POST"])
def api_save_tmdb_key():
    data = request.get_json(force=True)
    key = (data.get("key") or "").strip()
    try:
        cfg = {}
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH) as f:
                cfg = json.load(f)
        cfg["tmdb_api_key"] = key
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/tmdb/search")
def api_tmdb_search():
    key = get_tmdb_key()
    if not key:
        return jsonify({"error": "no_key"}), 403
    q = (request.args.get("q") or "").strip()
    media_type = request.args.get("type", "movie")  # 'movie' or 'tv'
    if not q:
        return jsonify([])
    try:
        params = urllib.parse.urlencode({"query": q, "api_key": key, "language": "en-US", "page": 1})
        endpoint = "search/tv" if media_type == "tv" else "search/movie"
        url = f"https://api.themoviedb.org/3/{endpoint}?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "statTRACK/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = json.loads(resp.read().decode())
        results = []
        for item in raw.get("results", [])[:12]:
            poster = item.get("poster_path")
            cover_url = f"https://image.tmdb.org/t/p/w300{poster}" if poster else None
            if media_type == "tv":
                title = item.get("name") or item.get("original_name", "")
                release = (item.get("first_air_date") or "")[:4]
            else:
                title = item.get("title") or item.get("original_title", "")
                release = (item.get("release_date") or "")[:4]
            rating = item.get("vote_average")
            results.append({
                "title": title,
                "year": release,
                "rating": round(rating, 1) if rating else None,
                "overview": item.get("overview") or None,
                "cover_url": cover_url,
                "genres": [],  # genre_ids only in search, skip
            })
        return jsonify(results)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return jsonify({"error": "invalid_key"}), 401
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/sidebar")
def api_sidebar():
    key = get_tmdb_key()
    result = {
        "has_tmdb": bool(key),
        "top_rated":  {"movies": [], "shows": [], "manga": [], "anime": [], "books": []},
        "top_airing": {"movies": [], "shows": [], "manga": [], "anime": [], "books": []},
    }

    def _tmdb_items(endpoint, limit=5, is_tv=False):
        url = f"https://api.themoviedb.org/3/{endpoint}?api_key={key}&language=en-US"
        req = urllib.request.Request(url, headers={"User-Agent": "statTRACK/1.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            raw = json.loads(resp.read().decode())
        items = []
        for item in raw.get("results", [])[:limit]:
            poster = item.get("poster_path")
            if is_tv:
                title = item.get("name") or item.get("original_name", "")
                year  = (item.get("first_air_date") or "")[:4]
            else:
                title = item.get("title") or item.get("original_title", "")
                year  = (item.get("release_date") or "")[:4]
            items.append({
                "title": title,
                "year": year,
                "rating": round(item.get("vote_average", 0), 1),
                "cover_url": f"https://image.tmdb.org/t/p/w185{poster}" if poster else None,
            })
        return items

    def _jikan_manga(filter_=None, limit=10):
        params = f"limit={limit}" + (f"&filter={filter_}" if filter_ else "")
        url = f"https://api.jikan.moe/v4/top/manga?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "statTRACK/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = json.loads(resp.read().decode())
        items = []
        for item in raw.get("data", [])[:limit]:
            cover = None
            try:
                cover = item["images"]["jpg"]["image_url"]
            except Exception:
                pass
            items.append({
                "title": item.get("title", ""),
                "rating": item.get("score"),
                "cover_url": cover,
            })
        return items

    def _ol_books(query, sort="rating", limit=10):
        params = urllib.parse.urlencode({
            "q": query,
            "sort": sort,
            "limit": limit,
            "fields": "title,author_name,cover_i,first_publish_year,ratings_average",
        })
        url = f"https://openlibrary.org/search.json?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "statTRACK/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = json.loads(resp.read().decode())
        items = []
        for doc in raw.get("docs", [])[:limit]:
            cover_i = doc.get("cover_i")
            cover_url = f"https://covers.openlibrary.org/b/id/{cover_i}-M.jpg" if cover_i else None
            rating = doc.get("ratings_average")
            items.append({
                "title": doc.get("title", ""),
                "year": doc.get("first_publish_year"),
                "rating": round(rating, 1) if rating else None,
                "cover_url": cover_url,
            })
        return items

    def _jikan_anime(filter_=None, limit=10):
        params = f"limit={limit}" + (f"&filter={filter_}" if filter_ else "")
        url = f"https://api.jikan.moe/v4/top/anime?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "statTRACK/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = json.loads(resp.read().decode())
        items = []
        for item in raw.get("data", [])[:limit]:
            cover = None
            try:
                cover = item["images"]["jpg"]["image_url"]
            except Exception:
                pass
            items.append({
                "title": item.get("title", ""),
                "rating": item.get("score"),
                "cover_url": cover,
            })
        return items

    if key:
        try:
            result["top_rated"]["movies"]  = _tmdb_items("movie/top_rated", limit=10)
        except Exception:
            pass
        try:
            result["top_airing"]["movies"] = _tmdb_items("movie/now_playing", limit=10)
        except Exception:
            pass
        try:
            result["top_rated"]["shows"]   = _tmdb_items("tv/top_rated", limit=10, is_tv=True)
        except Exception:
            pass
        try:
            result["top_airing"]["shows"]  = _tmdb_items("tv/on_the_air", limit=10, is_tv=True)
        except Exception:
            pass

    try:
        result["top_rated"]["manga"]  = _jikan_manga()
    except Exception:
        pass
    time.sleep(0.4)
    try:
        result["top_airing"]["manga"] = _jikan_manga(filter_="publishing")
    except Exception:
        pass
    time.sleep(0.4)
    try:
        result["top_rated"]["anime"]  = _jikan_anime()
    except Exception:
        pass
    time.sleep(0.4)
    try:
        result["top_airing"]["anime"] = _jikan_anime(filter_="airing")
    except Exception:
        pass

    try:
        result["top_rated"]["books"]  = _ol_books("subject:fiction")
    except Exception:
        pass
    try:
        result["top_airing"]["books"] = _ol_books("new fiction", sort="new")
    except Exception:
        pass

    return jsonify(result)


# ── Recommender API ───────────────────────────────────────────────────────────

@app.route("/api/recommend")
def api_recommend():
    _load_recommenders()
    movie_q = (request.args.get("movie") or "").strip()
    user_id_str = (request.args.get("user_id") or "").strip()
    n = int(request.args.get("n", 10))

    if not movie_q and not user_id_str:
        return jsonify({"error": "provide movie or user_id"}), 400

    user_id = None
    if user_id_str:
        try:
            user_id = int(user_id_str)
        except ValueError:
            return jsonify({"error": "user_id must be an integer"}), 400

    resolved_title = None
    if movie_q:
        resolved_title = _resolve_title(movie_q)
        if resolved_title is None:
            return jsonify({"error": f"Movie '{movie_q}' not found"}), 404

    recs = _rec.recommend(user_id=user_id, movie_title=resolved_title, n=n)
    if recs.empty:
        return jsonify({"results": [], "resolved_title": resolved_title})

    results = [
        {
            "title": row["title"],
            "genres": row["genres"].replace("|", ", "),
            "score": round(float(row["score"]), 4),
        }
        for _, row in recs.iterrows()
    ]
    return jsonify({"results": results, "resolved_title": resolved_title})


@app.route("/api/movies/search")
def api_movies_search():
    _load_recommenders()
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify([])
    matches = _movies[_movies["title"].str.contains(q, case=False, na=False)].head(8)
    results = [
        {
            "movieId": int(row["movieId"]),
            "title": row["title"],
            "genres": row["genres"].replace("|", ", "),
        }
        for _, row in matches.iterrows()
    ]
    return jsonify(results)


@app.route("/api/books/search")
def api_books_search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify([])
    try:
        params = urllib.parse.urlencode({
            "q": q,
            "limit": 12,
            "fields": "key,title,author_name,cover_i,first_publish_year,ratings_average,subject",
        })
        url = f"https://openlibrary.org/search.json?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "statTRACK/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = json.loads(resp.read().decode())
        results = []
        for doc in raw.get("docs", []):
            cover_i = doc.get("cover_i")
            cover_url = f"https://covers.openlibrary.org/b/id/{cover_i}-M.jpg" if cover_i else None
            rating = doc.get("ratings_average")
            results.append({
                "title": doc.get("title", ""),
                "author": ", ".join(doc.get("author_name", [])) or None,
                "cover_url": cover_url,
                "year": doc.get("first_publish_year"),
                "rating": round(rating, 1) if rating else None,
                "subjects": (doc.get("subject") or [])[:5],
            })
        return jsonify(results)
    except Exception:
        return jsonify([])


@app.route("/api/manga/search")
def api_manga_search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify([])
    try:
        params = urllib.parse.urlencode({"q": q, "limit": 10})
        url = f"https://api.jikan.moe/v4/manga?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "statTRACK/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = json.loads(resp.read().decode())
        results = []
        for item in raw.get("data", []):
            cover_url = None
            try:
                cover_url = item["images"]["jpg"]["image_url"]
            except (KeyError, TypeError):
                pass
            genres = [g.get("name", "") for g in item.get("genres", [])]
            results.append({
                "title": item.get("title", ""),
                "genres": genres,
                "cover_url": cover_url,
                "synopsis": item.get("synopsis") or None,
                "rating": item.get("score"),
            })
        return jsonify(results)
    except Exception:
        return jsonify([])


@app.route("/api/anime/search")
def api_anime_search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify([])
    try:
        params = urllib.parse.urlencode({"q": q, "limit": 10})
        url = f"https://api.jikan.moe/v4/anime?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "statTRACK/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = json.loads(resp.read().decode())
        results = []
        for item in raw.get("data", []):
            cover_url = None
            try:
                cover_url = item["images"]["jpg"]["image_url"]
            except (KeyError, TypeError):
                pass
            genres = [g.get("name", "") for g in item.get("genres", [])]
            results.append({
                "title": item.get("title", ""),
                "genres": genres,
                "cover_url": cover_url,
                "synopsis": item.get("synopsis") or None,
                "rating": item.get("score"),
                "year": str(item.get("year") or ""),
            })
        return jsonify(results)
    except Exception:
        return jsonify([])


@app.route("/api/recs/library")
def api_recs_library():
    import re as _re
    lib_items  = library_all()
    list_items = watchlist_all()
    all_items  = lib_items + list_items
    if not all_items:
        return jsonify([])

    exclude    = {i["title"].lower() for i in all_items}
    tmdb_key   = get_tmdb_key()

    # Seeds: all items sorted by rating desc (highest-rated = "because you liked X")
    by_type = {}
    all_sorted = sorted(lib_items, key=lambda x: x.get("rating") or 0, reverse=True) + list_items
    for item in all_sorted:
        t = item["type"]
        by_type.setdefault(t, [])
        if item["title"] not in by_type[t] and len(by_type[t]) < 6:
            by_type[t].append(item["title"])

    # ── Personalized fetchers (when type IS in library) ──────────────

    def run_movies(seeds):
        _load_recommenders()
        results = []
        for seed in seeds:
            resolved = _resolve_title(seed)
            if not resolved:
                continue
            try:
                recs = _rec.recommend(movie_title=resolved, n=6)
                for _, row in recs.iterrows():
                    if row["title"].lower() not in exclude:
                        results.append({
                            "title": row["title"], "type": "movie",
                            "score": None, "genres": row["genres"].replace("|", ", "),
                            "cover_url": None, "because": seed,
                        })
            except Exception:
                pass
        return results

    def run_jikan(jikan_type, seeds):
        results = []
        for title in seeds[:3]:
            try:
                params = urllib.parse.urlencode({"q": title, "limit": 1})
                req = urllib.request.Request(
                    f"https://api.jikan.moe/v4/{jikan_type}?{params}",
                    headers={"User-Agent": "statTRACK/1.0"})
                with urllib.request.urlopen(req, timeout=6) as r:
                    data = json.loads(r.read()).get("data", [])
                if not data:
                    continue
                mal_id = data[0]["mal_id"]
                time.sleep(0.4)
                req2 = urllib.request.Request(
                    f"https://api.jikan.moe/v4/{jikan_type}/{mal_id}/recommendations",
                    headers={"User-Agent": "statTRACK/1.0"})
                with urllib.request.urlopen(req2, timeout=6) as r:
                    rec_data = json.loads(r.read()).get("data", [])
                for rec in rec_data[:6]:
                    entry = rec.get("entry", {})
                    t = entry.get("title", "")
                    if not t or t.lower() in exclude:
                        continue
                    cover = None
                    try:
                        cover = entry["images"]["jpg"]["image_url"]
                    except Exception:
                        pass
                    results.append({
                        "title": t, "type": jikan_type,
                        "score": None, "genres": "", "cover_url": cover, "because": title,
                    })
            except Exception:
                pass
            time.sleep(0.4)
        return results

    def run_books(seeds):
        results = []
        for title in seeds:
            try:
                params = urllib.parse.urlencode({"q": title, "limit": 1, "fields": "subject"})
                req = urllib.request.Request(
                    f"https://openlibrary.org/search.json?{params}",
                    headers={"User-Agent": "statTRACK/1.0"})
                with urllib.request.urlopen(req, timeout=6) as r:
                    docs = json.loads(r.read()).get("docs", [])
                if not docs:
                    continue
                subjects = (docs[0].get("subject") or [])[:2]
                if not subjects:
                    continue
                params2 = urllib.parse.urlencode({
                    "q": f"subject:{subjects[0]}", "limit": 8,
                    "sort": "rating", "fields": "title,cover_i,ratings_average",
                })
                req2 = urllib.request.Request(
                    f"https://openlibrary.org/search.json?{params2}",
                    headers={"User-Agent": "statTRACK/1.0"})
                with urllib.request.urlopen(req2, timeout=6) as r:
                    docs2 = json.loads(r.read()).get("docs", [])
                for doc in docs2:
                    t = doc.get("title", "")
                    if not t or t.lower() in exclude:
                        continue
                    cover_i = doc.get("cover_i")
                    rating = doc.get("ratings_average")
                    results.append({
                        "title": t, "type": "book",
                        "score": round(rating, 1) if rating else None,
                        "genres": subjects[0],
                        "cover_url": f"https://covers.openlibrary.org/b/id/{cover_i}-M.jpg" if cover_i else None,
                        "because": title,
                    })
            except Exception:
                pass
        return results

    def run_shows(seeds, key):
        results = []
        for title in seeds[:3]:
            try:
                params = urllib.parse.urlencode({"query": title, "api_key": key, "language": "en-US"})
                req = urllib.request.Request(
                    f"https://api.themoviedb.org/3/search/tv?{params}",
                    headers={"User-Agent": "statTRACK/1.0"})
                with urllib.request.urlopen(req, timeout=6) as r:
                    data = json.loads(r.read()).get("results", [])
                if not data:
                    continue
                show_id = data[0]["id"]
                req2 = urllib.request.Request(
                    f"https://api.themoviedb.org/3/tv/{show_id}/similar?api_key={key}&language=en-US",
                    headers={"User-Agent": "statTRACK/1.0"})
                with urllib.request.urlopen(req2, timeout=6) as r:
                    sim_data = json.loads(r.read()).get("results", [])
                for item in sim_data[:6]:
                    t = item.get("name") or item.get("original_name", "")
                    if not t or t.lower() in exclude:
                        continue
                    poster = item.get("poster_path")
                    rating = item.get("vote_average")
                    results.append({
                        "title": t, "type": "show",
                        "score": round(rating, 1) if rating else None, "genres": "",
                        "cover_url": f"https://image.tmdb.org/t/p/w185{poster}" if poster else None,
                        "because": title,
                    })
            except Exception:
                pass
        return results

    # ── Trending fallbacks (when type is NOT in library) ─────────────

    def run_jikan_top(jikan_type):
        try:
            req = urllib.request.Request(
                f"https://api.jikan.moe/v4/top/{jikan_type}?limit=8",
                headers={"User-Agent": "statTRACK/1.0"})
            with urllib.request.urlopen(req, timeout=6) as r:
                data = json.loads(r.read()).get("data", [])
            results = []
            for item in data:
                t = item.get("title", "")
                if not t or t.lower() in exclude:
                    continue
                cover = None
                try:
                    cover = item["images"]["jpg"]["image_url"]
                except Exception:
                    pass
                results.append({
                    "title": t, "type": jikan_type,
                    "score": item.get("score"), "genres": "",
                    "cover_url": cover, "because": "Trending",
                })
            return results[:6]
        except Exception:
            return []

    def run_books_top():
        try:
            params = urllib.parse.urlencode({
                "q": "subject:fiction", "limit": 8, "sort": "rating",
                "fields": "title,cover_i,ratings_average",
            })
            req = urllib.request.Request(
                f"https://openlibrary.org/search.json?{params}",
                headers={"User-Agent": "statTRACK/1.0"})
            with urllib.request.urlopen(req, timeout=6) as r:
                docs = json.loads(r.read()).get("docs", [])
            results = []
            for doc in docs:
                t = doc.get("title", "")
                if not t or t.lower() in exclude:
                    continue
                cover_i = doc.get("cover_i")
                rating = doc.get("ratings_average")
                results.append({
                    "title": t, "type": "book",
                    "score": round(rating, 1) if rating else None, "genres": "",
                    "cover_url": f"https://covers.openlibrary.org/b/id/{cover_i}-M.jpg" if cover_i else None,
                    "because": "Trending",
                })
            return results[:6]
        except Exception:
            return []

    def run_shows_top(key):
        try:
            req = urllib.request.Request(
                f"https://api.themoviedb.org/3/tv/top_rated?api_key={key}&language=en-US",
                headers={"User-Agent": "statTRACK/1.0"})
            with urllib.request.urlopen(req, timeout=6) as r:
                data = json.loads(r.read()).get("results", [])
            results = []
            for item in data[:8]:
                t = item.get("name") or item.get("original_name", "")
                if not t or t.lower() in exclude:
                    continue
                poster = item.get("poster_path")
                rating = item.get("vote_average")
                results.append({
                    "title": t, "type": "show",
                    "score": round(rating, 1) if rating else None, "genres": "",
                    "cover_url": f"https://image.tmdb.org/t/p/w185{poster}" if poster else None,
                    "because": "Trending",
                })
            return results[:6]
        except Exception:
            return []

    def run_jikan_all():
        """Run anime then manga sequentially to respect Jikan rate limit."""
        results = []
        anime_res = run_jikan("anime", by_type["anime"]) if "anime" in by_type else []
        results.extend(anime_res or run_jikan_top("anime"))
        time.sleep(0.4)
        manga_res = run_jikan("manga", by_type["manga"]) if "manga" in by_type else []
        results.extend(manga_res or run_jikan_top("manga"))
        return results

    # ── Dispatch all fetchers in parallel ─────────────────────────────
    futures_map = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        if "movie" in by_type:
            futures_map[ex.submit(run_movies, by_type["movie"])] = "movie"
        futures_map[ex.submit(run_jikan_all)] = "jikan"
        if "book" in by_type:
            futures_map[ex.submit(run_books, by_type["book"])] = "book"
        else:
            futures_map[ex.submit(run_books_top)] = "book_top"
        if "show" in by_type and tmdb_key:
            futures_map[ex.submit(run_shows, by_type["show"], tmdb_key)] = "show"
        elif tmdb_key:
            futures_map[ex.submit(run_shows_top, tmdb_key)] = "show_top"

        all_results = []
        for future in concurrent.futures.as_completed(futures_map, timeout=25):
            try:
                all_results.extend(future.result())
            except Exception:
                pass

    seen = {}
    for r in all_results:
        key = (r["title"].lower(), r["type"])
        if key not in seen:
            seen[key] = r
        elif r.get("cover_url") and not seen[key].get("cover_url"):
            seen[key]["cover_url"] = r["cover_url"]

    # Balance across types so no single type crowds out others
    type_counts = {}
    final_recs = []
    for r in seen.values():
        t = r["type"]
        if type_counts.get(t, 0) < 6:
            final_recs.append(r)
            type_counts[t] = type_counts.get(t, 0) + 1

    # Batch-fetch TMDB posters for movie recs — strip "(year)" from MovieLens titles
    if tmdb_key:
        movie_recs = [r for r in final_recs if r["type"] == "movie" and not r.get("cover_url")]
        if movie_recs:
            def fetch_poster(rec):
                try:
                    clean = _re.sub(r'\s*\(\d{4}\)\s*$', '', rec["title"]).strip()
                    params = urllib.parse.urlencode({
                        "query": clean, "api_key": tmdb_key, "language": "en-US",
                    })
                    req = urllib.request.Request(
                        f"https://api.themoviedb.org/3/search/movie?{params}",
                        headers={"User-Agent": "statTRACK/1.0"})
                    with urllib.request.urlopen(req, timeout=4) as r:
                        results = json.loads(r.read()).get("results", [])
                    if results:
                        poster = results[0].get("poster_path")
                        if poster:
                            rec["cover_url"] = f"https://image.tmdb.org/t/p/w185{poster}"
                except Exception:
                    pass
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as poster_ex:
                concurrent.futures.wait(
                    [poster_ex.submit(fetch_poster, r) for r in movie_recs],
                    timeout=6,
                )

    return jsonify(final_recs)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=False, port=5001, use_reloader=False)

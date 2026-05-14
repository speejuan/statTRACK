#!/usr/bin/env python3
import argparse
import os
import shutil
import sys
import zipfile
import urllib.request

import pandas as pd

from recommender import (
    CollaborativeFilteringRecommender,
    ContentBasedRecommender,
    HybridRecommender,
)

DATA_URL = "https://files.grouplens.org/datasets/movielens/ml-latest-small.zip"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
MOVIES_CSV = os.path.join(DATA_DIR, "movies.csv")
RATINGS_CSV = os.path.join(DATA_DIR, "ratings.csv")
TAGS_CSV = os.path.join(DATA_DIR, "tags.csv")


def download_data():
    if os.path.exists(MOVIES_CSV):
        return
    print("Downloading MovieLens small dataset (~3 MB)...")
    os.makedirs(DATA_DIR, exist_ok=True)
    zip_path = os.path.join(DATA_DIR, "ml-latest-small.zip")
    try:
        urllib.request.urlretrieve(DATA_URL, zip_path)
    except Exception as e:
        print(f"Download failed: {e}")
        print(f"Please manually download from:\n  {DATA_URL}")
        print(f"and extract movies.csv, ratings.csv, tags.csv into {DATA_DIR}/")
        sys.exit(1)

    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(DATA_DIR)

    extracted = os.path.join(DATA_DIR, "ml-latest-small")
    for fname in ["movies.csv", "ratings.csv", "tags.csv", "links.csv"]:
        src = os.path.join(extracted, fname)
        if os.path.exists(src):
            shutil.move(src, os.path.join(DATA_DIR, fname))

    shutil.rmtree(extracted, ignore_errors=True)
    os.remove(zip_path)
    print("Dataset ready.\n")


def load_data():
    movies = pd.read_csv(MOVIES_CSV)
    ratings = pd.read_csv(RATINGS_CSV)
    tags = pd.read_csv(TAGS_CSV) if os.path.exists(TAGS_CSV) else None
    return movies, ratings, tags


def build_recommenders(movies, ratings, tags):
    print("Building recommendation models...")
    cb = ContentBasedRecommender(movies, tags)
    cf = CollaborativeFilteringRecommender(ratings, movies)
    hybrid = HybridRecommender(cb, cf, movies, ratings)
    print("Ready.\n")
    return cb, cf, hybrid


def print_recs(df, label):
    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
        print("  No recommendations found.\n")
        return
    width = 54
    print(f"\n{'─' * width}")
    print(f"  {label}")
    print(f"{'─' * width}")
    for i, row in df.iterrows():
        genres = row.get("genres", "").replace("|", ", ")
        print(f"  {i+1:2}. {row['title']}")
        print(f"      {genres}  |  score: {row['score']:.3f}")
    print(f"{'─' * width}\n")


def resolve_title(query, movies):
    """Return the exact title from movies df, or None."""
    if query in movies["title"].values:
        return query
    matches = movies[movies["title"].str.contains(query, case=False, na=False)]
    if matches.empty:
        return None
    return matches.iloc[0]["title"]


def interactive_mode(hybrid, cb, cf, movies, ratings):
    print("Movie Recommendation System")
    print("─" * 40)
    print("Commands:")
    print("  movie <title>           Find content-similar movies")
    print("  user <id>               CF recommendations for a user")
    print("  hybrid <id> <title>     Hybrid: user taste + movie seed")
    print("  search <term>           Search the movie catalog")
    print("  help                    Show this menu")
    print("  quit                    Exit")
    print()

    while True:
        try:
            raw = input(">> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not raw:
            continue

        parts = raw.split(maxsplit=1)
        action = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if action in ("quit", "exit", "q"):
            print("Bye!")
            break

        elif action == "help":
            print("  movie <title>           Find content-similar movies")
            print("  user <id>               CF recommendations for a user")
            print("  hybrid <id> <title>     Hybrid: user taste + movie seed")
            print("  search <term>           Search the movie catalog")
            print()

        elif action == "search":
            if not arg:
                print("  Usage: search <term>\n")
                continue
            matches = movies[movies["title"].str.contains(arg, case=False, na=False)]
            if matches.empty:
                print(f"  No movies found matching '{arg}'\n")
            else:
                print(f"\n  Found {min(len(matches), 15)} result(s):")
                for _, row in matches.head(15).iterrows():
                    genres = row["genres"].replace("|", ", ")
                    print(f"    [{row['movieId']:6}]  {row['title']}  —  {genres}")
                print()

        elif action == "movie":
            if not arg:
                print("  Usage: movie <title>\n")
                continue
            title = resolve_title(arg, movies)
            if title is None:
                print(f"  '{arg}' not found. Try: search {arg}\n")
                continue
            recs = cb.get_similar_movies(title, n=10)
            print_recs(recs, f"Content-similar to '{title}'")

        elif action == "user":
            try:
                uid = int(arg)
            except ValueError:
                print("  Usage: user <user_id>  (integer)\n")
                continue
            already = ratings[ratings["userId"] == uid]["movieId"].tolist()
            recs = cf.recommend_for_user(uid, n=10, already_rated=already)
            if recs.empty:
                print(f"  User {uid} not found in dataset.\n")
                continue
            print_recs(recs, f"CF recommendations for user {uid}")

        elif action == "hybrid":
            sub = arg.split(maxsplit=1)
            if len(sub) < 2:
                print("  Usage: hybrid <user_id> <movie_title>\n")
                continue
            try:
                uid = int(sub[0])
            except ValueError:
                print("  Usage: hybrid <user_id> <movie_title>\n")
                continue
            title = resolve_title(sub[1], movies)
            if title is None:
                print(f"  '{sub[1]}' not found. Try: search {sub[1]}\n")
                continue
            recs = hybrid.recommend(user_id=uid, movie_title=title, n=10)
            print_recs(recs, f"Hybrid recs  [user {uid} + '{title}']")

        else:
            print(f"  Unknown command '{action}'. Type 'help' for options.\n")


def main():
    parser = argparse.ArgumentParser(
        description="Movie Recommendation System (hybrid content-based + collaborative filtering)"
    )
    parser.add_argument("--movie", metavar="TITLE", help="Content-based: movies similar to TITLE")
    parser.add_argument("--user", metavar="ID", type=int, help="CF: recommendations for user ID")
    parser.add_argument("--n", metavar="N", type=int, default=10, help="Number of results (default 10)")
    args = parser.parse_args()

    download_data()
    movies, ratings, tags = load_data()
    cb, cf, hybrid = build_recommenders(movies, ratings, tags)

    if args.movie and args.user:
        title = resolve_title(args.movie, movies)
        if title is None:
            print(f"Movie '{args.movie}' not found.")
            sys.exit(1)
        recs = hybrid.recommend(user_id=args.user, movie_title=title, n=args.n)
        print_recs(recs, f"Hybrid recs  [user {args.user} + '{title}']")

    elif args.movie:
        title = resolve_title(args.movie, movies)
        if title is None:
            print(f"Movie '{args.movie}' not found.")
            sys.exit(1)
        recs = cb.get_similar_movies(title, n=args.n)
        print_recs(recs, f"Content-similar to '{title}'")

    elif args.user:
        already = ratings[ratings["userId"] == args.user]["movieId"].tolist()
        recs = cf.recommend_for_user(args.user, n=args.n, already_rated=already)
        if recs.empty:
            print(f"User {args.user} not found in dataset.")
            sys.exit(1)
        print_recs(recs, f"CF recommendations for user {args.user}")

    else:
        interactive_mode(hybrid, cb, cf, movies, ratings)


if __name__ == "__main__":
    main()

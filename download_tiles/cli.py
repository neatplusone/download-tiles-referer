import click
import logging
from pathlib import Path
import re
import requests
import sqlite3
import sys
import time
import urllib
from concurrent.futures import ThreadPoolExecutor
from math import floor, log, tan, pi, cos

APPLICATION_ID = 0x4D504258
DEFAULT_TILES_URL = "http://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
DEFAULT_ATTRIBUTION = "© OpenStreetMap contributors"


def parse_zoom_levels(ctx, param, value):
    r = re.compile(r"^(\d+)(?:\-(\d+))?$")
    match = r.match(value)
    if match is None:
        raise click.BadParameter(
            "zoom-levels should be a single number or a 3-7 number range"
        )
    low, high = match.groups()
    low = int(low)
    if high is None:
        high = low
    else:
        high = int(high)
    if high < low:
        raise click.BadParameter("zoom-levels should be a low-high range")
    if high > 24:
        raise click.BadParameter("Maximum zoom level is 24")
    return low, high


def parse_bbox(ctx, param, value):
    float_re = r"(\-?(?:\d+)(?:\.\d+)?)"
    r = re.compile(r"^()\s*,\s*()\s*,\s*()\s*,\s*()$".replace("()", float_re))
    match = r.match(value)
    if match is None:
        raise click.BadParameter("bbox should be min-lon,min-lat,max-lon,max-lat")
    min_lon, min_lat, max_lon, max_lat = map(float, match.groups())
    return min_lon, min_lat, max_lon, max_lat


def validate_tiles_url(ctx, param, value):
    if not value:
        return value
    fragments = "{z}", "{x}", "{y}"
    for fragment in fragments:
        if fragment not in value:
            raise click.BadParameter(
                "tiles-url should include {}".format(", ".join(fragments))
            )
    return value


def deg2num(lat_deg, lon_deg, zoom):
    lat_deg = max(min(85.0511, lat_deg), -85.0511)
    lat_rad = lat_deg * pi / 180
    n = 2.0**zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - log(tan(lat_rad) + (1 / cos(lat_rad))) / pi) / 2.0 * n)
    return (xtile, ytile)


@click.command()
@click.argument(
    "mbtiles", type=click.Path(dir_okay=False, file_okay=True), required=False
)
@click.option(
    "-z",
    "--zoom-levels",
    default="0-3",
    callback=parse_zoom_levels,
    help="Zoom levels - defaults to 0-3",
)
@click.option(
    "-b",
    "--bbox",
    default="-180.0,-90.0,180.0,90.0",
    callback=parse_bbox,
    help="Bounding box of tiles to retrieve: min-lon,min-lat,max-lon,max-lat",
)
@click.option(
    "--tiles-url",
    help="Tile URL server to use. Defaults to OpenStreetMap.",
    callback=validate_tiles_url,
)
@click.option(
    "--tiles-subdomains",
    help="Subdomains to use in the {s} parameter.",
    default="a,b,c",
    callback=lambda ctx, param, value: [v.strip() for v in value.split(",")],
)
@click.option(
    "--country",
    help="Country to find bounding box for",
)
@click.option(
    "--city",
    help="City to find bounding box for",
)
@click.option(
    "--show-bbox",
    is_flag=True,
    help="Show country or city bounding box without downloading tiles",
)
@click.option(
    "--user-agent",
    default="github.com/simonw/download-tiles",
    help="User-Agent header to send with tile requests",
)
@click.option(
    "--referer",
    default="",
    help="Referer header to send with tile requests, blocks --user-agent",
)
@click.option(
    "--attribution",
    help="Attribution to write to the metadata table",
)
@click.option(
    "--name",
    help="Name to write to the metadata table",
)
@click.option("--verbose", is_flag=True, help="Verbose mode - show detailed logs")
@click.option("--cache-dir", help="Folder to cache tiles between runs")
@click.option(
    "--skip-on-failure",
    is_flag=True,
    help="Continue downloading other tiles if some tiles fail (e.g., 404 errors)",
)
@click.option(
    "--thread-count",
    type=int,
    default=10,
    help="Number of download threads (default: 10, lower values reduce database lock issues)",
)
@click.option(
    "--overwrite",
    is_flag=True,
    help="Overwrite existing mbtiles file if it already exists.",
)
@click.option(
    "--log-failed-urls-to",
    type=click.Path(dir_okay=False, file_okay=True),
    help="File to log URLs of failed tiles to",
)
@click.option(
    "--continue",
    "continue_download",
    is_flag=True,
    help="If mbtiles file exists, continue downloading from where it left off.",
)
@click.version_option()
def cli(
    mbtiles,
    zoom_levels,
    bbox,
    tiles_url,
    tiles_subdomains,
    country,
    city,
    show_bbox,
    user_agent,
    attribution,
    name,
    verbose,
    cache_dir,
    referer,
    skip_on_failure,
    thread_count,
    overwrite,
    log_failed_urls_to,
    continue_download,
):
    """
    Download map tiles and store them in an MBTiles database.

    Please use this tool responsibly, and respect the OpenStreetMap tile usage policy:
    https://operations.osmfoundation.org/policies/tiles/
    """
    # mbtiles is required unless show_bbox is used
    if not mbtiles and not show_bbox:
        raise click.BadParameter("mbtiles argument is required")
    if overwrite and continue_download:
        raise click.BadParameter("Cannot use --overwrite and --continue at the same time.")
    if continue_download and mbtiles and Path(mbtiles).exists():
        pass
    elif mbtiles and Path(mbtiles).exists():
        raise click.BadParameter(
            f"{mbtiles} already exists. Use --overwrite to overwrite it or --continue to continue downloading."
        )
    suggested_name = None
    if country:
        bbox, suggested_name = lookup_bbox("country", country)
    elif city:
        bbox, suggested_name = lookup_bbox("city", city)
    if show_bbox:
        click.echo(",".join(map(str, bbox)))
        return
    if not attribution and not tiles_url:
        attribution = DEFAULT_ATTRIBUTION
    if verbose:
        logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)
    if referer != "":
        headers = {"Referer": referer}
    else:
        headers = {"User-Agent": user_agent}

    db = sqlite3.connect(str(mbtiles))
    db.execute(
        "CREATE TABLE IF NOT EXISTS tiles (zoom_level integer, tile_column integer, tile_row integer, tile_data blob, primary key (zoom_level, tile_column, tile_row))"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS metadata (name text primary key, value text)"
    )
    db.close()

    min_lon, min_lat, max_lon, max_lat = bbox

    for zoom in range(zoom_levels[0], zoom_levels[1] + 1):
        top_left = deg2num(max_lat, min_lon, zoom)
        bottom_right = deg2num(min_lat, max_lon, zoom)

        x_min, y_min = top_left
        x_max, y_max = bottom_right

        tiles = []
        for x in range(x_min, x_max + 1):
            for y in range(y_min, y_max + 1):
                if continue_download:
                    db = sqlite3.connect(str(mbtiles))
                    cursor = db.cursor()
                    cursor.execute(
                        "SELECT 1 FROM tiles WHERE zoom_level = ? AND tile_column = ? AND tile_row = ?",
                        (zoom, x, y),
                    )
                    if cursor.fetchone():
                        continue
                    db.close()
                tiles.append((zoom, x, y))

        with ThreadPoolExecutor(max_workers=thread_count) as executor:
            for _ in executor.map(
                lambda p: download_tile(p, tiles_url, tiles_subdomains, headers, mbtiles, skip_on_failure, verbose, cache_dir, log_failed_urls_to),
                tiles,
            ):
                pass

    # Set application_id with retry logic and longer timeout
    max_retries = 5
    retry_delay = 1.0

    for attempt in range(max_retries):
        try:
            db = sqlite3.connect(str(mbtiles), timeout=30.0)
            db.execute("PRAGMA journal_mode=WAL")  # Enable WAL mode for better concurrency
            with db:
                application_id = db.execute("pragma application_id").fetchone()[0]
                if not application_id:
                    db.execute("pragma application_id = {}".format(APPLICATION_ID))
            db.close()
            break
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and attempt < max_retries - 1:
                if verbose:
                    click.echo(f"Database locked, retrying in {retry_delay} seconds...", err=True)
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                raise

    if name is None:
        name = suggested_name

    if attribution or name or bbox:
        if attribution == "osm":
            attribution = DEFAULT_ATTRIBUTION

        for attempt in range(max_retries):
            try:
                db = sqlite3.connect(str(mbtiles), timeout=30.0)
                db.execute("PRAGMA journal_mode=WAL")
                with db:
                    # Ensure metadata table exists
                    db.execute(
                        "CREATE TABLE IF NOT EXISTS metadata (name text primary key, value text)"
                    )
                    if attribution:
                        db.execute(
                            "insert or replace into metadata (name, value) values (:name, :value)",
                            {"name": "attribution", "value": attribution},
                        )
                    if name:
                        db.execute(
                            "insert or replace into metadata (name, value) values (:name, :value)",
                            {"name": "name", "value": name},
                        )
                    if bbox:
                        db.execute(
                            "insert or replace into metadata (name, value) values (:name, :value)",
                            {"name": "bounds", "value": ",".join(map(str, bbox))},
                        )
                db.close()
                break
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    if verbose:
                        click.echo(f"Database locked, retrying in {retry_delay} seconds...", err=True)
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    raise

def download_tile(tile, tiles_url, tiles_subdomains, headers, mbtiles, skip_on_failure, verbose, cache_dir, log_failed_urls_to):
    zoom, x, y = tile
    url = (tiles_url or DEFAULT_TILES_URL).format(
        s=tiles_subdomains[0], z=zoom, x=x, y=y
    )
    if cache_dir:
        cache_path = Path(cache_dir) / f"{zoom}-{x}-{y}.png"
        if cache_path.exists():
            with open(cache_path, "rb") as f:
                tile_data = f.read()
            db = sqlite3.connect(str(mbtiles))
            db.execute(
                "INSERT OR IGNORE INTO tiles (zoom_level, tile_column, tile_row, tile_data) VALUES (?, ?, ?, ?)",
                (zoom, x, y, tile_data),
            )
            db.commit()
            db.close()
            return

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        tile_data = response.content
        if cache_dir:
            with open(cache_path, "wb") as f:
                f.write(tile_data)
        db = sqlite3.connect(str(mbtiles))
        db.execute(
            "INSERT OR IGNORE INTO tiles (zoom_level, tile_column, tile_row, tile_data) VALUES (?, ?, ?, ?)",
            (zoom, x, y, tile_data),
        )
        db.commit()
        db.close()
    except requests.exceptions.RequestException as e:
        if skip_on_failure:
            if verbose:
                click.echo(f"Warning: Failed to download tile {zoom}/{x}/{y}: {e}", err=True)
            if log_failed_urls_to and e.response and e.response.status_code == 404:
                with open(log_failed_urls_to, "a") as f:
                    f.write(f"{url}\n")
        else:
            raise


def lookup_bbox(parameter, value):
    url = "https://nominatim.openstreetmap.org/?{}={}&format=json&limit=1".format(
        parameter, urllib.parse.quote_plus(value)
    )
    results = requests.get(url).json()
    boundingbox = results[0]["boundingbox"]
    lat1, lat2, lon1, lon2 = map(float, boundingbox)
    min_lat = min(lat1, lat2)
    max_lat = max(lat1, lat2)
    min_lon = min(lon1, lon2)
    max_lon = max(lon1, lon2)
    return (min_lon, min_lat, max_lon, max_lat), results[0]["display_name"]

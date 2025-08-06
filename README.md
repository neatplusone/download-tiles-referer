# download-tiles

[![PyPI](https://img.shields.io/pypi/v/download-tiles.svg)](https://pypi.org/project/download-tiles/)
[![Changelog](https://img.shields.io/github/v/release/simonw/download-tiles?include_prereleases&label=changelog)](https://github.com/simonw/download-tiles/releases)
[![Tests](https://github.com/simonw/download-tiles/workflows/Test/badge.svg)](https://github.com/simonw/download-tiles/actions?query=workflow%3ATest)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/simonw/download-tiles/blob/master/LICENSE)

Download map tiles and store them in an MBTiles database

## Installation

Unlike the root repository, you cannot install this fork from `pip`. Download this repo, unzip, go to its directory in the terminal / command prompt and install using pip:

```bash
# Install directly with pipx (recommended) or pip
pipx install .

# Or, for development with editable install
pip install -e .

# Or, to build a wheel first using standards-based tools
pip install build
python -m build
pip install dist/download_tiles-*.whl
```

Requires Python 3.8+ and `pip`.

To uninstall:

```bash
pip uninstall download-tiles
```

## Usage for Mapy.cz

Include the `--referer="https://mapy.cz/"` option. Then, you can download from Mapy.cz with the following URLs:
```bash
--tiles-url=https://mapserver.mapy.cz/base-m/{z}-{x}-{y}        //základní
--tiles-url=https://mapserver.mapy.cz/base-en/{z}-{x}-{y}       //base (en)
--tiles-url=https://mapserver.mapy.cz/turist-m/{z}-{x}-{y}      //turistická
--tiles-url=https://mapserver.mapy.cz/winter-m-down/{z}-{x}-{y} //zimní
--tiles-url=https://mapserver.mapy.cz/zemepis-m/{z}-{x}-{y}     //zeměpisná
--tiles-url=https://mapserver.mapy.cz/bing/{z}-{x}-{y}          //letecká (jpeg, untested)
--tiles-url=https://mapserver.mapy.cz/hybrid-base-m/{z}-{x}-{y} //průhledná základní přes leteckou
etc.
```

See below how to select output file, zoom levels, bounding box etc.

**Example:**

```bash
download-tiles --referer="https://mapy.cz/" --tiles-url=https://mapserver.mapy.cz/base-m/{z}-{x}-{y} --zoom-levels=8-10 --country=czechia --cache-dir=tmp "Česko základní.mbtiles"
download-tiles --referer="https://mapy.cz/" --tiles-url=https://mapserver.mapy.cz/turist-m/{z}-{x}-{y} --zoom-levels=14 --bbox=15.02,50.44,15.34,50.66 --cache-dir=tmp "Český ráj turistická.mbtiles"
```

The `--cache-dir` parameter is recommended: if the command fails (it sometimes does because of "database locked" issues I couldn't fix), you can retry it and it will finish without re-downloading already saved tiles.

To convert the result to a big PNG, open the Python shell (command `python` in terminal) and write the following (example for zoom-10 Czech Republic from "Česko základní.mbtiles"):
```python
from landez import ImageExporter
ie = ImageExporter(mbtiles_file="Česko základní.mbtiles")
ie.export_image(bbox=(12.09,48.55,18.87,51.06), zoomlevel=10, imagepath="Česko základní 10.png")
```

## Usage

This tool downloads tiles from a specified [TMS (Tile Map Server)](https://wiki.openstreetmap.org/wiki/TMS) server for a specified bounding box and range of zoom levels and stores those tiles in a MBTiles SQLite database. It is a command-line wrapper around the [Landez](https://github.com/makinacorpus/landez) Python libary.

**Please use this tool responsibly**. Consult the usage policies of the tile servers you are interacting with, for example the [OpenStreetMap Tile Usage Policy](https://operations.osmfoundation.org/policies/tiles/).

Running the following will download zoom levels 0-3 of OpenStreetMap, 85 tiles total, and store them in a SQLite database called `world.mbtiles`:
```bash
download-tiles world.mbtiles
```
You can customize which tile and zoom levels are downloaded using command options:
```
--zoom-levels=0-3
```
The different zoom levels to download. Specify a single number, e.g. `15`, or a range of numbers e.g. `0-4`. Be careful with this setting as you can easily go over the limits requested by the underlying tile server.
```
--bbox=3.9,-6.3,14.5,10.2
```
The bounding box to fetch. Should be specified as `min-lon,min-lat,max-lon,max-lat`. You can use [bboxfinder.com](http://bboxfinder.com/) to find these for different areas.
```
--city=london
```
Or:
```
--country=madagascar
```

These options can be used instead of `--bbox`. The city or country specified will be looked up using the [Nominatum API](https://nominatim.org/release-docs/latest/api/Search/) and used to derive a bounding box.
```
--show-bbox
```
Use this option to output the bounding box that was retrieved for the `--city` or `--country` without downloading any tiles.
```
--name=Name
```
A name for this tile collection, used for the `name` field in the `metadata` table. If not specified a UUID will be used, or if you used `--city` or `--country` the name will be set to the full name of that place.
```
--attribution="Attribution string"
```

Attribution string to bake into the `metadata` table. This will default to `© OpenStreetMap contributors` unless you use `--tiles-url` to specify an alternative tile server, in which case you should specify a custom attribution string.

You can use the `--attribution=osm` shortcut to specify the `© OpenStreetMap contributors` value without having to type it out in full.
```
--tiles-url=https://...
```
The tile server URL to use. This should include `{z}` and `{x}` and `{y}` specifiers, and can optionally include `{s}` for subdomains.

The default URL used here is for OpenStreetMap, `http://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png`
```
--tiles-subdomains=a,b,c
```
A comma-separated list of subdomains to use for the `{s}` parameter.
```
--verbose
```
Use this option to turn on verbose logging.
```
--cache-dir=/tmp/tiles
```
Provide a directory to cache downloaded tiles between runs. This can be useful if you are worried you might not have used the correct options for the bounding box or zoom levels.
```
--skip-on-failure
```
Continue downloading other tiles if some tiles fail (e.g., 404 errors). When this flag is set, the tool will skip missing or unavailable tiles instead of stopping the entire download process. This is useful when working with tile servers that may have incomplete coverage or temporary availability issues.
```
--thread-count=10
```
Number of download threads to use (default: 10). Lower values can help prevent SQLite database locking issues when downloading many tiles, especially at higher zoom levels. If you encounter "database is locked" errors, try reducing this value (e.g., `--thread-count=5`).

Databases created with this tool will have their SQLite `application_id` set to `0x4d504258`, as described in the SQLite [magic.txt file](https://www.sqlite.org/src/artifact?ci=trunk&filename=magic.txt).

## Known Issues

### pkg_resources deprecation warning (FIXED)
The landez library (v2.5.0) uses the deprecated `pkg_resources.parse_version`. This has been addressed in this fork by:
- Suppressing the deprecation warning
- Monkey-patching to use the modern `packaging.version.parse` instead
- The warning should no longer appear when running the tool

### Database locking with high zoom levels
When downloading many tiles (especially at zoom levels 10+), you may encounter SQLite "database is locked" errors. To mitigate this:
- Use `--thread-count=5` or lower to reduce concurrent writes
- Use `--skip-on-failure` to continue despite errors
- Use `--cache-dir` to enable retrying failed downloads

## Development

To contribute to this tool, first checkout the code. Then create a new virtual environment:
```bash
cd download-tiles
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```
Or if you are using `pipenv`:
```bash
pipenv shell
```
Now install the package in development mode with test dependencies:
```bash
# Install in editable mode with test dependencies
pip install -e '.[test]'
```
To run the tests:
```bash
pytest
```

To build the package for distribution:
```bash
# Install build tools
pip install build twine

# Build the package
python -m build

# This creates wheel and source distributions in dist/
ls dist/
```

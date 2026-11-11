"""Offline transport GIS tools using explicit source files and metric projections.

Inputs are two-dimensional WGS84 GeoJSON FeatureCollections. Distance and area
operations use the caller's ``projected_crs`` (a projected CRS with metre axes),
which must be appropriate to the study area. Outputs return WGS84 geometries.
Geocoding is an exact lookup in a supplied point gazetteer, not a web service.
"""
from copy import deepcopy
import json
import math
from pathlib import Path

from pyproj import CRS, Transformer
from shapely.geometry import Point, mapping, shape
from shapely.ops import transform
from shapely.validation import explain_validity


def _number(value, name, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{name} must be a finite number')
    if not math.isfinite(value) or value < minimum:
        raise ValueError(f'{name} must be finite and >= {minimum}')
    return float(value)


def _coordinates(geometry):
    if not isinstance(geometry, dict):
        raise ValueError('Every feature needs a non-null geometry')
    if geometry.get('type') == 'GeometryCollection':
        children = geometry.get('geometries')
        if not isinstance(children, list) or not children:
            raise ValueError('Empty or malformed GeometryCollection')
        for child in children:
            yield from _coordinates(child)
        return

    def walk(value):
        if not isinstance(value, (list, tuple)) or not value:
            raise ValueError('Empty or malformed coordinates')
        if isinstance(value[0], (int, float)):
            if len(value) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float))
                                      or not math.isfinite(v) for v in value):
                raise ValueError('Coordinates must contain two finite numbers: longitude, latitude')
            yield value
        else:
            for child in value:
                yield from walk(child)

    yield from walk(geometry.get('coordinates'))


def _geometry(value):
    for lon, lat in _coordinates(value):
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError('Coordinates are outside WGS84 longitude/latitude bounds')
    try:
        geometry = shape(value)
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise ValueError(f'Invalid GeoJSON geometry: {exc}') from exc
    if geometry.is_empty or not geometry.is_valid:
        raise ValueError(f'Invalid geometry: {explain_validity(geometry)}')
    return geometry


def _load(params, key='file'):
    try:
        path = Path(params[key])
    except (KeyError, TypeError) as exc:
        raise ValueError(f'{key} must name an input GeoJSON file') from exc
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict) or value.get('type') != 'FeatureCollection':
        raise ValueError(f'{key} must be a GeoJSON FeatureCollection')
    if 'crs' in value:
        raise ValueError('Input GeoJSON must use WGS84 coordinates without a legacy crs member')
    if not isinstance(value.get('features'), list):
        raise ValueError('FeatureCollection.features must be an array')
    rows = []
    for index, feature in enumerate(value['features']):
        if not isinstance(feature, dict) or feature.get('type') != 'Feature':
            raise ValueError(f'Feature {index} is not a GeoJSON Feature')
        properties = feature.get('properties')
        if properties is not None and not isinstance(properties, dict):
            raise ValueError(f'Feature {index} properties must be an object or null')
        try:
            geometry = _geometry(feature.get('geometry'))
        except ValueError as exc:
            raise ValueError(f'Feature {index}: {exc}') from exc
        rows.append((index, feature, geometry))
    return rows


def _projection(params):
    if not params.get('projected_crs'):
        raise ValueError('projected_crs is required for metric spatial operations')
    crs = CRS.from_user_input(params['projected_crs'])
    if not crs.is_projected or len(crs.axis_info) != 2 or any(
            not math.isclose(axis.unit_conversion_factor, 1.0, rel_tol=0, abs_tol=1e-12)
            for axis in crs.axis_info):
        raise ValueError('projected_crs must be a two-dimensional projected CRS with metre axes')
    forward = Transformer.from_crs(4326, crs, always_xy=True)
    backward = Transformer.from_crs(crs, 4326, always_xy=True)

    def convert(geometry, converter):
        result = transform(lambda x, y, z=None: converter.transform(x, y, errcheck=True), geometry)
        if not result.is_valid or result.is_empty or not all(math.isfinite(v) for v in result.bounds):
            raise ValueError('Coordinate transformation produced an invalid geometry')
        return result

    return crs, lambda g: convert(g, forward), lambda g: convert(g, backward)


def _source(index, feature):
    return {'index': index, 'id': feature.get('id'), 'properties': deepcopy(feature.get('properties'))}


def _feature(geometry, properties):
    return {'type': 'Feature', 'properties': properties,
            'geometry': json.loads(json.dumps(mapping(geometry), allow_nan=False))}


def _collection(features, crs, operation):
    return {'type': 'FeatureCollection', 'features': features,
            'analysis': {'operation': operation, 'projected_crs': crs.to_string(),
                         'distance_unit': 'metre', 'output_crs': 'EPSG:4326'}}


def geocoding(params):
    """Find exact name/address matches and return all candidates on ambiguity."""
    query = params.get('query')
    if not isinstance(query, str) or not query.strip():
        raise ValueError('query must be a non-empty string')
    query = query.strip()
    fields = params.get('fields', ['name', 'address'])
    if not isinstance(fields, list) or not fields or any(not isinstance(v, str) or not v for v in fields):
        raise ValueError('fields must be a non-empty list of property names')
    candidates = []
    for index, feature, geometry in _load(params):
        if geometry.geom_type != 'Point':
            raise ValueError('Geocoding requires a point gazetteer; non-point locations need an explicit point')
        properties = feature.get('properties') or {}
        matches = [field for field in fields if isinstance(properties.get(field), str)
                   and properties[field].strip() == query]
        if matches:
            candidates.append({'source': _source(index, feature), 'matched_fields': matches,
                               'coordinates': [geometry.x, geometry.y]})
    status = 'not_found' if not candidates else ('matched' if len(candidates) == 1 else 'ambiguous')
    return {'status': status, 'query': query, 'match': 'exact', 'output_crs': 'EPSG:4326',
            'candidates': candidates}


def spatial_search(params):
    """Select features whose projected geometry is at most radius_m from center."""
    center = params.get('center')
    if not isinstance(center, (list, tuple)) or len(center) != 2:
        raise ValueError('center must be [longitude, latitude]')
    point = _geometry({'type': 'Point', 'coordinates': center})
    radius = _number(params.get('radius_m'), 'radius_m')
    crs, forward, _ = _projection(params)
    projected_point = forward(point)
    features = []
    for index, feature, geometry in _load(params):
        distance = projected_point.distance(forward(geometry))
        if distance <= radius:
            features.append(_feature(geometry, {'source': _source(index, feature), 'distance_m': distance}))
    features.sort(key=lambda feature: (feature['properties']['distance_m'],
                                      feature['properties']['source']['index']))
    return _collection(features, crs, 'distance_search')


def buffer(params):
    """Buffer each source geometry independently in a projected metre CRS."""
    radius = _number(params.get('radius_m'), 'radius_m')
    if radius == 0:
        raise ValueError('Buffer radius_m must be greater than zero')
    crs, forward, backward = _projection(params)
    features = []
    for index, feature, geometry in _load(params):
        result = backward(forward(geometry).buffer(radius, quad_segs=32))
        # Catch projections which transform buffered vertices out of valid WGS84 bounds.
        _geometry(mapping(result))
        features.append(_feature(result, {'source': _source(index, feature), 'radius_m': radius}))
    return _collection(features, crs, 'buffer')


def overlay(params):
    """Intersect every overlapping input pair, retaining both source records."""
    if params.get('operation', 'intersection') != 'intersection':
        raise ValueError('Overlay currently supports operation="intersection"')
    crs, forward, backward = _projection(params)
    left = [(i, feature, forward(geometry)) for i, feature, geometry in _load(params)]
    right = [(i, feature, forward(geometry)) for i, feature, geometry in _load(params, 'other_file')]
    features = []
    for i, a, ga in left:
        for j, b, gb in right:
            if not ga.intersects(gb):
                continue
            intersection = ga.intersection(gb)
            if intersection.is_empty:
                continue
            result = backward(intersection)
            _geometry(mapping(result))
            features.append(_feature(result, {'left': _source(i, a), 'right': _source(j, b),
                                             'area_m2': intersection.area}))
    return _collection(features, crs, 'intersection')


TOOLS = {'Geocoding': geocoding, 'Spatial Search': spatial_search, 'Buffer': buffer, 'Overlay': overlay}
FILE_PARAMETERS = {'Geocoding': ('file',), 'Spatial Search': ('file',), 'Buffer': ('file',),
                   'Overlay': ('file', 'other_file')}

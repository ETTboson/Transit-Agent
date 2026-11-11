import json
from pathlib import Path
import tempfile
import unittest

from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform

from agent.tools import transit_spatial as spatial


class TransitSpatialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.inverse = Transformer.from_crs(32619, 4326, always_xy=True)
        self.forward = Transformer.from_crs(4326, 32619, always_xy=True)
        self.x, self.y = self.forward.transform(-71.0, 42.0)

    def tearDown(self):
        self.tmp.cleanup()

    def point(self, dx, dy=0, name='stop'):
        return {'type': 'Feature', 'id': f'{dx},{dy}', 'properties': {'name': name},
                'geometry': {'type': 'Point', 'coordinates': list(self.inverse.transform(self.x + dx, self.y + dy))}}

    def polygon(self, xmin, ymin, xmax, ymax, properties):
        xy = [(xmin,ymin), (xmax,ymin), (xmax,ymax), (xmin,ymax), (xmin,ymin)]
        return {'type': 'Feature', 'properties': properties, 'geometry': {'type': 'Polygon',
                'coordinates': [[list(self.inverse.transform(self.x+x, self.y+y)) for x,y in xy]]}}

    def write(self, filename, features):
        path = self.folder / filename
        path.write_text(json.dumps({'type': 'FeatureCollection', 'features': features}), encoding='utf-8')
        return str(path)

    def test_exact_geocoding_preserves_ambiguity_and_source(self):
        features = [self.point(0, name='Station'), self.point(150, name='Station'), self.point(300, name='Other')]
        features[2]['properties']['address'] = '20 High Street'
        file = self.write('stops.geojson', features)
        result = spatial.geocoding({'file': file, 'query': 'Station'})
        self.assertEqual(result['status'], 'ambiguous')
        self.assertEqual(len(result['candidates']), 2)
        self.assertEqual([row['source']['index'] for row in result['candidates']], [0, 1])
        self.assertEqual(result['candidates'][0]['source']['properties'], {'name': 'Station'})
        result = spatial.geocoding({'file': file, 'query': '20 High Street'})
        self.assertEqual(result['status'], 'matched')
        self.assertEqual(result['candidates'][0]['matched_fields'], ['address'])
        self.assertEqual(spatial.geocoding({'file': file, 'query': 'station'})['status'], 'not_found')
        self.assertEqual(spatial.geocoding({'file': file, 'query': 'Missing'})['candidates'], [])

    def test_distance_search_uses_metres_and_sorts_nearest(self):
        file = self.write('stops.geojson', [self.point(200), self.point(50), self.point(100)])
        result = spatial.spatial_search({'file': file, 'center': [-71,42], 'radius_m': 110,
                                         'projected_crs': 'EPSG:32619'})
        distances = [f['properties']['distance_m'] for f in result['features']]
        self.assertEqual(len(distances), 2)
        self.assertAlmostEqual(distances[0], 50, places=5)
        self.assertAlmostEqual(distances[1], 100, places=5)
        self.assertEqual(result['features'][0]['properties']['source']['index'], 1)
        self.assertEqual(result['features'][0]['geometry']['type'], 'Point')
        self.assertEqual(result['analysis']['distance_unit'], 'metre')

    def test_buffer_returns_wgs84_with_metric_radius(self):
        file = self.write('point.geojson', [self.point(0)])
        result = spatial.buffer({'file': file, 'radius_m': 100, 'projected_crs': 'EPSG:32619'})
        polygon = shape(result['features'][0]['geometry'])
        self.assertTrue(polygon.is_valid)
        self.assertLess(abs(polygon.centroid.x + 71), .00001)
        metric = transform(self.forward.transform, polygon)
        self.assertAlmostEqual(metric.bounds[2] - metric.bounds[0], 200, places=5)
        self.assertAlmostEqual(metric.bounds[3] - metric.bounds[1], 200, places=5)
        self.assertEqual(result['features'][0]['properties']['source']['properties'], {'name': 'stop'})

    def test_overlay_intersects_and_keeps_both_provenances(self):
        a = self.write('left.geojson', [self.polygon(0,0,200,200,{'name':'A', 'source':'keep A'})])
        b = self.write('right.geojson', [self.polygon(100,0,300,200,{'name':'B', 'source':'keep B'}),
                                       self.polygon(500,0,700,200,{'name':'C'})])
        result = spatial.overlay({'file': a, 'other_file': b, 'projected_crs': 'EPSG:32619'})
        self.assertEqual(len(result['features']), 1)
        props = result['features'][0]['properties']
        self.assertEqual(props['left']['properties']['name'], 'A')
        self.assertEqual(props['right']['properties']['source'], 'keep B')
        self.assertAlmostEqual(props['area_m2'], 20000, places=3)
        self.assertEqual(props['right']['index'], 0)

    def test_metre_crs_is_required(self):
        file = self.write('point.geojson', [self.point(0)])
        for crs in [None, 'EPSG:4326', 'EPSG:2249']:
            with self.subTest(crs=crs), self.assertRaises(ValueError):
                spatial.buffer({'file': file, 'radius_m': 100, 'projected_crs': crs})

    def test_invalid_geojson_and_geometry_are_rejected(self):
        bad = self.folder / 'bad.geojson'
        inputs = [
            {'type':'Point','coordinates':[-71,42]},
            {'type':'FeatureCollection','crs':None,'features':[]},
            {'type':'FeatureCollection','features':[{'type':'Feature','properties':{},'geometry':None}]},
            {'type':'FeatureCollection','features':[{'type':'Feature','properties':{},'geometry':
                {'type':'Point','coordinates':[500000,4649776]}}]},
            {'type':'FeatureCollection','features':[{'type':'Feature','properties':{},'geometry':
                {'type':'Point','coordinates':[float('nan'),42]}}]},
            {'type':'FeatureCollection','features':[{'type':'Feature','properties':{},'geometry':
                {'type':'Polygon','coordinates':[[[0,0],[1,1],[1,0],[0,1],[0,0]]]}}]},
        ]
        for value in inputs:
            with self.subTest(value=value):
                bad.write_text(json.dumps(value), encoding='utf-8')
                with self.assertRaises(ValueError):
                    spatial.buffer({'file': str(bad), 'radius_m': 10, 'projected_crs': 'EPSG:32619'})

    def test_missing_geocoding_input_and_unsupported_options(self):
        file = self.write('empty.geojson', [])
        for query in ['', None, 1]:
            with self.subTest(query=query), self.assertRaises(ValueError):
                spatial.geocoding({'file': file, 'query': query})
        for radius in [-1, float('inf'), True, '100', 0]:
            with self.subTest(radius=radius), self.assertRaises(ValueError):
                spatial.buffer({'file': file, 'radius_m': radius, 'projected_crs': 'EPSG:32619'})
        with self.assertRaises(ValueError):
            spatial.overlay({'file': file, 'other_file': file, 'projected_crs': 'EPSG:32619', 'operation':'union'})
        polygon = self.write('polygon.geojson', [self.polygon(0,0,10,10,{'name':'block'})])
        with self.assertRaisesRegex(ValueError, 'point gazetteer'):
            spatial.geocoding({'file': polygon, 'query': 'block'})

    def test_empty_spatial_inputs_return_empty_collections(self):
        file = self.write('empty.geojson', [])
        self.assertEqual(spatial.spatial_search({'file': file, 'center': [-71,42], 'radius_m': 0,
                          'projected_crs':'EPSG:32619'})['features'], [])
        self.assertEqual(spatial.buffer({'file':file, 'radius_m':100,
                          'projected_crs':'EPSG:32619'})['features'], [])
        self.assertEqual(spatial.overlay({'file':file, 'other_file':file,
                          'projected_crs':'EPSG:32619'})['features'], [])


if __name__ == '__main__':
    unittest.main()

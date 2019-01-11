import os
import json
import threading
import requests
import traceback

import geojson
import pyproj

from shapely.geometry import shape, GeometryCollection
from shapely.ops import transform
from pyproj import Proj
from xml.etree import ElementTree


def handler(context, event):

    b = event.body
    if not isinstance(b, dict):
        body = json.loads(b.decode('utf-8-sig'))
    else:
        body = b
    
    context.logger.info("Event received !")

    try:

        # if we're not ready to handle this request yet, deny it
        if not FunctionState.done_loading:
            context.logger.warn_with('Function not ready, denying request !')
            raise NuclioResponseError(
                'The service is loading and is temporarily unavailable.',requests.codes.unavailable)

        max_width, max_height = None, None
        if 'Svg-Max-Width' in event.headers and 'Svg-Max-Height' in event.headers:
            max_width = int(event.headers['Svg-Max-Width'])
            max_height = int(event.headers['Svg-Max-Height'])

        # get the GeoJSON (as a feature collection) to render
        doc = Helpers.parse_body(context,body)

        source = Proj(init=FunctionConfig.source_crs)
        target = Proj(init=FunctionConfig.target_crs)
        reproject = lambda x,y: pyproj.transform(source,target,x,y)

        zoom = []
        geoms = [transform(reproject,shape(f['geometry'])) for f in doc['features']]

        for i, f in enumerate(doc['features']):
            if 'plot' in f['properties']:
                geoms[i].plot = f['properties']['plot']
            if 'inZoomBox' in f['properties'] and f['properties']['inZoomBox']:
                #zoom.append(transform(reproject,shape(f['geometry'])))
                zoom.append(geoms[i])
                geoms[i].plot['fill'] = '#000000'

        zoom_box = GeometryCollection(zoom).envelope.buffer(150).envelope if len(zoom) != 0 else None

        svg_data = Helpers.to_svg(geoms,zoom_box,max_width,max_height) if (max_width and max_height) else Helpers.to_svg(geoms,zoom_box)

        context.logger.info("'{0}' geometries rendered as SVG".format(len(geoms)))

    except NuclioResponseError as error:
        return error.as_response(context)

    except Exception as error:
        context.logger.warn_with('Unexpected error occurred, responding with internal server error',
            exc=str(error))
        message = 'Unexpected error occurred: {0}\n{1}'.format(error, traceback.format_exc())
        return NuclioResponseError(message).as_response(context)

    return context.Response(body=svg_data,
                            headers={},
                            content_type='image/svg+xml',
                            status_code=requests.codes.ok)


class FunctionConfig(object):

    default_svg_viewport_width= None

    default_svg_viewport_height= None

    # CRS of GeoJSON inputs
    source_crs = 'EPSG:4326'

    # CRS of the SVG rendering
    target_crs = 'EPSG:3857'


class FunctionState(object):

    done_loading = False


class Helpers(object):

    @staticmethod
    def to_svg(geometries, envelope=None, max_width=300, max_height=300):

        svg_top = '<svg xmlns="http://www.w3.org/2000/svg" ' \
            'xmlns:xlink="http://www.w3.org/1999/xlink" '
        
        if len(geometries) == 0:
            return svg_top + '/>'
        else:
            geometry = GeometryCollection(geometries)
            # Establish SVG canvas that will fit all the data + small space
            xmin, ymin, xmax, ymax = geometry.bounds
            if xmin == xmax and ymin == ymax:
                # This is a point; buffer using an arbitrary size
                xmin, ymin, xmax, ymax = geometry.buffer(1).bounds
            else:
                # Expand bounds by a fraction of the data ranges
                expand = 0.04  # or 4%, same as R plots
                widest_part = max([xmax - xmin, ymax - ymin])
                expand_amount = widest_part * expand
                xmin -= expand_amount
                ymin -= expand_amount
                xmax += expand_amount
                ymax += expand_amount
            dx = xmax - xmin
            dy = ymax - ymin
            width = min([max([100., dx]), max_width])
            height = min([max([100., dy]), max_height])
            try:
                scale_factor = max([dx, dy]) / max([width, height])
            except ZeroDivisionError:
                scale_factor = 1.

            view_box, transform = None, None
            if envelope:
                xxmin, yymin, xxmax, yymax = envelope.bounds
                view_box = "{} {} {} {}".format(xxmin, yymin, xxmax-xxmin, yymax-yymin)
                transform = "matrix(1,0,0,-1,0,{})".format(yymax + yymin)
            else:
                view_box = "{} {} {} {}".format(xmin, ymin, dx, dy)
                transform = "matrix(1,0,0,-1,0,{})".format(ymax + ymin)
            
            l = []
            for g in geometries:
                svg = g.svg(scale_factor)
                if hasattr(g,'plot'):
                    xml = ElementTree.fromstring(svg)
                    for v in g.plot:
                        xml.set(v,g.plot[v])
                    svg = ElementTree.tostring(xml).decode()
                l.append(svg)
                                
            body = '<g>' + ''.join(l) + '</g>'

            return('{0} width="{2}" height="{3}" viewBox="{1}" '
                   'preserveAspectRatio="xMidYMid meet">'
                   '<g transform="{4}">{5}</g></svg>'
                ).format(svg_top,view_box, width, height, transform, body)

    @staticmethod
    def load_configs():

        FunctionConfig.default_svg_viewport_width = os.getenv('DEFAULT_SVG_VIEWPORT_WIDTH',300)

        FunctionConfig.default_svg_viewport_height = os.getenv('DEFAULT_SVG_VIEWPORT_HEIGHT',300)

    @staticmethod
    def parse_body(context, body):

        # check if it's a valid GeoJSON
        try:
            geodoc = geojson.loads(json.dumps(body))
        except Exception as error:
            context.logger.warn_with("Loading body's request as a GeoJSON failed.")
            raise NuclioResponseError(
                "Loading body's request as a GeoJSON failed.",requests.codes.bad)

        if not (isinstance(geodoc,geojson.feature.FeatureCollection) and geodoc.is_valid):
            context.logger.warn_with("The provided GeoJSON is not a valid 'FeatureCollection'.")
            raise NuclioResponseError(
                "The provided GeoJSON is not a valid 'FeatureCollection'.",requests.codes.bad)

        return geodoc

    @staticmethod
    def on_import():

        Helpers.load_configs()
        FunctionState.done_loading = True


class NuclioResponseError(Exception):

    def __init__(self, description, status_code=requests.codes.internal_server_error):
        self._description = description
        self._status_code = status_code

    def as_response(self, context):
        return context.Response(body=self._description,
                                headers={},
                                content_type='text/plain',
                                status_code=self._status_code)


t = threading.Thread(target=Helpers.on_import)
t.start()

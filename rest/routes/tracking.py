import requests
import xml.etree.ElementTree as ET
import gzip

from flask import Blueprint, json, make_response, jsonify
from skyfield.api import EarthSatellite, load, utc, wgs84
from datetime import datetime, timedelta
from pytz import timezone
from ..services.helpers import (
  datetime_range, download, get_comment_value, format_epoch, chunks, deg_to_compass, calculate_twinlites
)

bp = Blueprint('tracking', __name__, url_prefix='/tracking')

@bp.route('')
def index():
  ts = load.timescale()
  norad = requests.get("https://celestrak.org/NORAD/elements/gp.php?NAME=ISS%20(ZARYA)&FORMAT=TLE").text.splitlines()
  satellite = EarthSatellite(norad[1], norad[2], norad[0], ts)

  f = open("log/track-log-" + datetime.today().strftime("%Y-%m-%d %H:%M:%S") + ".txt", "w")
  res = []

  current_date = datetime.now(tz=utc)

  for t in datetime_range(current_date, current_date + timedelta(days=5), timedelta(minutes=4)):
    geocentric = satellite.at(ts.from_datetime(t))
    
    obj = {
      'time': t.strftime("%Y-%m-%dT%H:%M:%S.%f"),
      'position': geocentric.position.km.tolist(),
      'velocity': geocentric.velocity.km_per_s.tolist(),
      'location': str(geocentric.subpoint())
    }

    f.write(obj['time'] 
    + "\n\t\tPosition: " + str(obj['position'])
    + "\n\t\tVelocity: " + str(obj['velocity'])
    + "\n\t\tLocation: " + obj['location']
    + "\n")

    res.append(obj)

  f.close()

  return jsonify(res)

@bp.route('/nasa')
def getNasaData():
  download("https://nasa-public-data.s3.amazonaws.com/iss-coords/current/ISS_OEM/ISS.OEM_J2K_EPH.xml")
  result = ET.parse("log/ISS.OEM_J2K_EPH.xml").getroot().find("oem").find("body").find("segment")
  metadata = result.find("metadata")
  comments = result.find("data").findall("COMMENT")
  state_vectors = result.find("data").findall("stateVector")

  obj = {
    'id': metadata.find("OBJECT_ID").text,
    'name': metadata.find("OBJECT_NAME").text,
    'centerName': metadata.find("CENTER_NAME").text,
    'mass': get_comment_value(comments[1].text),
    'dragArea': get_comment_value(comments[2].text),
    'gragCoefficient': get_comment_value(comments[3].text), 
    'solarRadArea': get_comment_value(comments[4].text), 
    'solarRadCoefficient': get_comment_value(comments[5].text),
    'epoches': list(map(format_epoch, state_vectors[0:1550:]))
  }

  content = gzip.compress(json.dumps(obj, separators=(',', ':')).encode('utf8'), 9)
  response = make_response(content)
  response.headers['Content-length'] = len(content)
  response.headers['Content-Encoding'] = 'gzip'
  return response

@bp.route('/tle-predict-for-location')
def getTLEPredictedSightings():
  zone = timezone('US/Central')
  ts = load.timescale()
  norad = requests.get("https://celestrak.org/NORAD/elements/gp.php?NAME=ISS%20(ZARYA)&FORMAT=TLE").text.splitlines()
  iss = EarthSatellite(norad[1], norad[2], norad[0], ts)
  location = wgs84.latlon(30.266666, -97.733330)
  t0 = ts.from_datetime(zone.localize(datetime.fromisoformat('2023-02-03')))
  t1 = ts.from_datetime(zone.localize(datetime.fromisoformat('2023-02-19')))
  t, events = iss.find_events(location, t0, t1, 10)
  
  res = []

  for event in chunks(list(zip(t, events)), 3):
    ti0, _ = event[0]
    ti1, _ = event[1]
    ti2, _ = event[2]

    twinlites = calculate_twinlites(location, ti1.astimezone(zone), zone)

    if twinlites[0] < ti1.astimezone(zone) < twinlites[2] or twinlites[4] < ti1.astimezone(zone) < twinlites[7]:
      maxHeight, _, _ = (iss - location).at(ti1).altaz()
      appears_altitude, appears_azimut, _ = (iss - location).at(ti0).altaz()
      disappears_altitude, disappears_azimut, _ = (iss - location).at(ti2).altaz()

      item = {
        'date': ti0.astimezone(zone).strftime('%a %b %-d, %-I:%M %p'),
        'maxHeight': round(maxHeight.degrees),
        'appears': str(round(appears_altitude.degrees)) + " " + deg_to_compass(appears_azimut.degrees),
        'disappears': str(round(disappears_altitude.degrees)) + " " + deg_to_compass(disappears_azimut.degrees),
        'visible': round((ti2.astimezone(zone) - ti0.astimezone(zone)).seconds / 60)
      }

      res.append(item)

  return jsonify(res)
    
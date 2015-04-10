# -*- coding: utf-8 -*-

from sqlalchemy import func, Integer, String, DateTime, Float
from sqlalchemy.ext.hybrid import hybrid_method
from sqlalchemy.orm.exc import MultipleResultsFound, NoResultFound
from sqlalchemy.sql import select, column

from ..decorators import cacher

from .. import db

class ItemLocation(object):
    """This class can be used as base for the implementing SQL tables"""

    id           = db.Column('id', String(50), primary_key=True)
    latitude     = db.Column('latitude', Float)
    longitude    = db.Column('longitude', Float)
    method       = db.Column('method', String(50))
    locable      = db.Column('locable', Integer)
    city         = db.Column('city', String(255))
    region       = db.Column('region', String(255))
    country      = db.Column('country', String(255))
    country_code = db.Column('country_code', String(2))
    info         = db.Column('info', String(255))
    modified     = db.Column('modified', DateTime)

    def __repr__(self):
        return '<ItemLocation: (%s) in %f,%f>' % (self.id, self.latitude, self.longitude)

    @hybrid_method
    @cacher
    def get(self, id):
        """Get a valid Location Item from id"""
        try:
            return self.query.get(id)
        except NoResultFound:
            return None

    # Get location subquery using the spherical law of cosines
    # faster than Vincenty and Haversine and done in the bbdd side
    # http://jsperf.com/vincenty-vs-haversine-distance-calculations/2
    #
    #  Does a first "cut" before getting results from the mysql table
    #  as described here:
    #  http://www.movable-type.co.uk/scripts/latlong-db.html
    #
    #  @Cacher cannot be applied here, this only returns a subquery to be executed
    #  from the calling entity
    @hybrid_method
    def location_subquery(self, latitude, longitude, radius, fields=['id'], locable_only=True):
        from math import degrees, radians, cos

        R = 6371 # earth's mean radius, km
        latitude = float(latitude)
        longitude = float(longitude)
        radius = float(radius)
        # first-cut bounding box (in degrees)
        maxLat = latitude + degrees(radius/R)
        minLat = latitude - degrees(radius/R)
        # compensate for degrees longitude getting smaller with increasing latitude
        maxLon = longitude + degrees(radius/R/cos(radians(latitude)))
        minLon = longitude - degrees(radius/R/cos(radians(latitude)))
        filters = [self.latitude.between(minLat, maxLat), self.longitude.between(minLon, maxLon)]
        if locable_only:
            filters.append(self.locable == True)
         # acos(sin(:lat)*sin(radians(Lat)) + cos(:lat)*cos(radians(Lat))*cos(radians(Lon)-:lon)) * :R
        rlat = radians(latitude)
        rlng = radians(longitude)
        distance = (
            func.acos(
                  func.sin(rlat)
                * func.sin(func.radians(column('latitude')))
                + func.cos(rlat)
                * func.cos(func.radians(column('latitude')))
                * func.cos(func.radians(column('longitude')) - rlng)
            ) * R
        ).label('distance')
        subquery = db.session.query(self.id,self.latitude,self.longitude,self.method,self.city,self.country,self.country_code,self.modified,distance).filter(*filters).subquery('FirstCut')
        # print "\n--\n"; print subquery; print "\n-->--\n";
        sub = select(fields).select_from(subquery).where(distance <= radius)#
        # print sub; print "\n--<--\n";
        return sub

    # Vincenty Method, slightly better precision, high cost on querying database
    @hybrid_method
    @cacher
    def location_ids(self, latitude, longitude, radius, locable_only = True):
        from geopy.distance import VincentyDistance
        from math import degrees, radians, cos

        R = 6371 # earth's mean radius, km
        latitude = float(latitude)
        longitude = float(longitude)
        radius = float(radius)
        # first-cut bounding box (in degrees)
        maxLat = latitude + degrees(radius/R)
        minLat = longitude - degrees(radius/R)
        # compensate for degrees longitude getting smaller with increasing latitude
        maxLon = longitude + degrees(radius/R/cos(radians(latitude)))
        minLon = longitude - degrees(radius/R/cos(radians(latitude)))
        filters = [self.latitude.between(minLat, maxLat), self.longitude.between(minLon, maxLon)]
        if locable_only:
            filters.append(self.locable == True)

        locations = self.query.filter(*filters).all()

        locations = filter(lambda l: VincentyDistance((latitude, longitude), (l.latitude, l.longitude)).km <= radius, locations)
        location_ids = map(lambda l: int(l.id), locations)

        return location_ids

#####################
## IMPLEMENTATIONS
#####################

class UserLocation(db.Model, ItemLocation):
    """User location particular case"""
    __tablename__ = 'user_location'

    id = db.Column('id', String(50), db.ForeignKey('user.id'), primary_key=True)

    def __repr__(self):
        return '<UserLocation: (%s) in %f,%f>' % (self.id, self.latitude, self.longitude)


class ProjectLocation(db.Model, ItemLocation):
    """Project location particular case"""
    __tablename__ = 'project_location'

    id = db.Column('id', String(50), db.ForeignKey('project.id'), primary_key=True)

    def __repr__(self):
        return '<ProjectLocation: (%s) in %f,%f>' % (self.id, self.latitude, self.longitude)
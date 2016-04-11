# -*- coding: utf-8 -*-
from sqlalchemy import func, Integer, String, Date, DateTime, Boolean
from sqlalchemy.ext.hybrid import hybrid_property, hybrid_method
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound
from sqlalchemy import asc, desc, and_, or_, distinct
from sqlalchemy.orm import aliased

from ..cacher import cacher
from ..helpers import image_url, utc_from_local, user_url, get_lang, objectview

from ..categories.models import Category, CategoryLang
from ..invests.models import Invest
from ..models.node import Node
from ..models.message import Message
from ..location.models import UserLocation

from hashlib import sha1
from passlib.context import CryptContext

from .. import db

# User stuff
class User(db.Model):
    __tablename__ = 'user'

    id = db.Column('id', String(50), primary_key=True)
    password_hash = db.Column('password', String(255))
    name = db.Column('name', String(100))
    avatar = db.Column('avatar', String(255))
    email = db.Column('email', String(255))
    active = db.Column('active', Boolean)
    hide = db.Column('hide', Boolean)
    node = db.Column('node', String(50), db.ForeignKey(Node.id))
    created = db.Column('created', Date)
    updated = db.Column('modified', Date)


    def __repr__(self):
        return '<User %s: %r>' % (self.id, self.name)


    @hybrid_property
    def profile_image_url(self):
        return image_url(self.avatar)

    @hybrid_property
    def profile_url(self):
        return user_url(self.id)

    @hybrid_property
    def date_created(self):
        return utc_from_local(self.created)

    @hybrid_property
    def date_updated(self):
        return utc_from_local(self.updated)

    @hybrid_method
    def get_context(self):
        myctx = CryptContext(schemes=["bcrypt"], bcrypt__default_rounds=12)
        return myctx

    @hybrid_method
    def hash_password(self, password):
        """Hashes password. Passswords are pre-sha1 encoded"""
        sha = sha1(password.encode('utf-8'))
        self.password_hash = self.get_context().encrypt(sha.hexdigest())
        return self.password_hash

    @hybrid_method
    def verify_password(self, password):
        """Verifies password. Passswords are pre-sha1 encoded"""

        sha = sha1(password.encode('utf-8'))
        try:
            (ok, update) = self.get_context().verify_and_update(sha.hexdigest(), self.password_hash)
        except ValueError:
            print('old ' + self.password_hash)
            # Old plain SHA-1 database stored password
            ok = sha.hexdigest() == self.password_hash
            update = self.get_context().encrypt(self.password_hash)
        if ok and update:
            # update database
            self.password_hash = update
        return ok

    @hybrid_property
    def filters(self):
        return [self.hide == 0, self.active == 1]

    # Getting filters for this model
    @hybrid_method
    def get_filters(self, **kwargs):
        filters = self.filters
        if 'unsubscribed' in kwargs and kwargs['unsubscribed'] is not None:
            filters = [or_(self.hide == 1, self.active == 0)]

        # Filters by goteo node
        if 'node' in kwargs and kwargs['node'] is not None:
            filters.append(self.node.in_(kwargs['node']))
        # Filters by "from date"
        # counting users created after this date
        if 'from_date' in kwargs and kwargs['from_date'] is not None:
            filters.append(self.created >= kwargs['from_date'])
        # Filters by "to date"
        # counting users created before this date
        if 'to_date' in kwargs and kwargs['to_date'] is not None:
            filters.append(self.created <= kwargs['to_date'])
        # Filters by "project"
        # counting attached (invested or collaborated) to some project(s)
        if 'project' in kwargs and kwargs['project'] is not None:
            #TODO: solo usuarios que cuyo pago ha si "exitoso"
            # adding users "invested in"
            sub_invest = db.session.query(Invest.user_id).filter(Invest.project.in_(kwargs['project']))
            # adding users "collaborated in"
            sub_message = db.session.query(Message.user).filter(Message.project.in_(kwargs['project']))
            filters.append(or_(self.id.in_(sub_invest), self.id.in_(sub_message)))
        # filter by user interests
        if 'category' in kwargs and kwargs['category'] is not None:
            sub_interest = db.session.query(UserInterest.user).filter(UserInterest.interest.in_(kwargs['category']))
            filters.append(self.id.in_(sub_interest))
        #Filter by location
        if 'location' in kwargs and kwargs['location'] is not None:
            #location ids where to search
            subquery = UserLocation.location_subquery(**kwargs['location'])
            filters.append(UserLocation.id.in_(subquery))
            filters.append(UserLocation.id == self.id)

        #TODO: more filters, like creators, invested, etc
        return filters

    @hybrid_method
    @cacher
    def get(self, user_id):
        """Get a valid user form id"""
        try:
            filters = list(self.filters)
            filters.append(self.id == user_id)
            return self.query.filter(*filters).one()
        except NoResultFound:
            return None

    @hybrid_method
    @cacher
    def list(self, **kwargs):
        """Get a list of valid users"""
        try:
            limit = kwargs['limit'] if 'limit' in kwargs else 10
            page = kwargs['page'] if 'page' in kwargs else 0
            filters = list(self.get_filters(**kwargs))
            return self.query.distinct().filter(*filters).order_by(asc(self.id)).offset(page * limit).limit(limit).all()
        except NoResultFound:
            return []

    @hybrid_method
    @cacher
    def total(self, **kwargs):
        """Returns the total number of valid users"""
        try:
            filters = list(self.get_filters(**kwargs))
            count = db.session.query(func.count(distinct(self.id))).filter(*filters).scalar()
            if count is None:
                count = 0
            return count
        except MultipleResultsFound:
            return 0

    @hybrid_method
    @cacher
    def donors_by_project(self, project_id, **kwargs):
        """Get a list of valid donors for project"""
        try:
            limit = kwargs['limit'] if 'limit' in kwargs else 10
            page = kwargs['page'] if 'page' in kwargs else 0
            del kwargs['project']
            filters = list(self.get_filters(**kwargs))
            filters.append(Invest.user_id==self.id)
            filters.append(Invest.project==project_id)
            # return self.query.distinct().filter(*filters).order_by(asc(self.id)).offset(page * limit).limit(limit).all()
            return [d._asdict() for d in db.session.query(Invest.anonymous, \
                                                                        self.id, \
                                                                        self.name, \
                                                                        self.avatar, \
                                                                        self.active, \
                                                                        self.hide, \
                                                                        self.node, \
                                                                        self.created, \
                                                                        self.updated) \
                                                    .filter(*filters). \
                                                    order_by(asc(self.id)). \
                                                    offset(page * limit). \
                                                    limit(limit)]
        except NoResultFound:
            return []

    @hybrid_method
    @cacher
    def donors_by_project_total(self, project_id, **kwargs):
        """Returns the total number of valid of valid donors for project"""
        try:
            del kwargs['project']
            filters = list(self.get_filters(**kwargs))
            filters.append(Invest.user_id==self.id)
            filters.append(Invest.project==project_id)
            count = db.session.query(func.count(distinct(self.id))).filter(*filters).scalar()
            if count is None:
                count = 0
            return count
        except MultipleResultsFound:
            return 0

#User roles
class UserRole(db.Model):
    __tablename__ = 'user_role'

    user_id = db.Column('user_id', String(50), db.ForeignKey('user.id'), primary_key=True)
    role_id = db.Column('role_id', String(50), primary_key=True)
    node_id = db.Column('node_id', String(50), db.ForeignKey('node.id'))

    def __repr__(self):
        return '<UserRole %s: %s>' % (self.user_id, self.role_id)


#Api keys
class UserApi(db.Model):
    __tablename__ = 'user_api'

    user = db.Column('user_id', String(50), db.ForeignKey('user.id'), primary_key=True)
    key = db.Column('key', String(50))
    expiration_date = db.Column('expiration_date', DateTime)

    def __repr__(self):
        return '<UserApi: %s %s (%s)>' % (self.user, self.key, self.expiration_date)

# User interest
class UserInterest(db.Model):
    __tablename__ = 'user_interest'

    user = db.Column('user', String(50), db.ForeignKey('user.id'), primary_key=True)
    interest = db.Column('interest', Integer, db.ForeignKey('category.id'), primary_key=True)

    def __repr__(self):
        return '<UserInterest from %s to category %s>' % (self.user, self.interest)

    # Getting filters for this model
    @hybrid_method
    def get_filters(self, **kwargs):
        filters = [Category.name != '']  # para categorias
        if 'from_date' in kwargs and kwargs['from_date'] is not None:
            filters.append(Invest.date_invested >= kwargs['from_date'])
            filters.append(Invest.user_id == self.user)
        if 'to_date' in kwargs and kwargs['to_date'] is not None:
            filters.append(Invest.date_invested <= kwargs['to_date'])
            filters.append(Invest.user_id == self.user)
        if 'project' in kwargs and kwargs['project'] is not None:
            filters.append(Invest.project.in_(kwargs['project']))
            filters.append(Invest.user_id == self.user)
        if 'node' in kwargs and kwargs['node'] is not None:
            #TODO: project_node o invest_node?
            filters.append(User.id == self.user)
            filters.append(User.node.in_(kwargs['node']))
        if 'category' in kwargs and kwargs['category'] is not None:
            filters.append(self.interest.in_(kwargs['category']))
        if 'location' in kwargs and kwargs['location'] is not None:
            # Filtra por la localización del usuario
            subquery = UserLocation.location_subquery(**kwargs['location'])
            filters.append(self.user == UserLocation.id)
            filters.append(UserLocation.id.in_(subquery))
        return filters

    # Categories list
    @hybrid_method
    @cacher
    def categories(self, **kwargs):
        # In case of requiring languages, a LEFT JOIN must be generated
        cols = [func.count(self.user).label('users'), Category.id, Category.name]
        filters = list(self.get_filters(**kwargs))
        # In case of requiring languages, a LEFT JOIN must be generated
        if 'lang' in kwargs and kwargs['lang'] is not None:
            joins = []
            for l in kwargs['lang']:
                alias = aliased(CategoryLang)
                cols.append(alias.name.label('name_' + l))
                joins.append((alias, and_(alias.id == Category.id, alias.lang == l)))
            query = db.session.query(*cols).join(Category, Category.id == self.interest).outerjoin(*joins)
        else:
            query = db.session.query(*cols).join(Category, Category.id == self.interest)
        ret = []

        for u in query.filter(*filters).group_by(self.interest)\
                      .order_by(desc(func.count(self.user))):
            u = u._asdict()
            if 'lang' in kwargs and kwargs['lang'] is not None:
                u['name'] = get_lang(u, 'name', kwargs['lang'])
            ret.append(objectview(u))

        return ret

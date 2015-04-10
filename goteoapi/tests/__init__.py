from .. import app
from nose.tools import eq_

app.config['TESTING'] = True

test_app = app.test_client()

__import__('goteoapi.controllers')


def check_content_type(headers):
  eq_(headers['Content-Type'], 'application/json')


# def teardown():
#   # db_session.remove()
#   pass
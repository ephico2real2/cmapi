"""Stateful admin API model; no HTTP, database, Keycloak or containers."""
import contextlib
import copy
import importlib.util
import io
import os
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path(os.environ.get('SYNC_SCRIPT', ROOT / 'cmapi/src/cmapi/tools/realm_sync.py'))
spec = importlib.util.spec_from_file_location('rs_review', SOURCE)
rs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rs)
SECRET = 'unchanged-secret-181'


class RealmModel:
    def __init__(self, count=1):
        self.clients = [{'id': str(i), 'clientId': 'client-' + str(i), 'directAccessGrantsEnabled': True, 'secret': SECRET,
                         'serviceAccountsEnabled': False, 'publicClient': False, 'attributes': {'keep': 'unchanged'}} for i in range(count)]
        self.clients[-1]['clientId'] = 'cmapi-automation'
        self.writes = []
        self.bot = {'id': 'old-bot', 'username': 'bot-user', 'enabled': True, 'credentials': [{'type': 'password', 'value': 'old-password'}]}
        self.role = False
        self.sa = False

    def get(self, path, **kwargs):
        params = kwargs.get('params', {})
        if path == '/clients':
            if 'clientId' in params:
                name = params['clientId']
                if name in ('realm-management', 'audience'):
                    return [{'id': name, 'clientId': name}]
                return [copy.deepcopy(c) for c in self.clients if c['clientId'] == name]
            first = params.get('first', 0)
            return copy.deepcopy(self.clients[first:first + params.get('max', len(self.clients))])
        if path.endswith('/roles'):
            return [{'id': 'onboard', 'name': 'cmapi-onboarding'}]
        if path.endswith('/service-account-user'):
            assert self.sa, 'service account was requested before it was enabled'
            return {'id': 'sa'}
        if '/role-mappings/clients/' in path:
            return [{'id': 'onboard', 'name': 'cmapi-onboarding'}] if self.role else []
        if path == '/users':
            return [copy.deepcopy(self.bot)] if self.bot else []
        raise AssertionError(path)

    def call(self, method, path, **kwargs):
        data = kwargs.get('json')
        self.writes.append((method, path, copy.deepcopy(data)))
        if method == 'PUT' and path.startswith('/clients/'):
            client = next(c for c in self.clients if c['id'] == path.rsplit('/', 1)[1])
            client.update(copy.deepcopy(data))
            if client['clientId'] == 'cmapi-automation' and client['serviceAccountsEnabled']:
                self.sa = True  # ClientResource.updateClientServiceAccount / ClientManager.enableServiceAccount
        elif method == 'POST' and '/role-mappings/clients/' in path:
            self.role = True
        elif method == 'DELETE' and path == '/users/old-bot':
            self.bot = None
        else:
            raise AssertionError((method, path))


class SyncSecurityTests(unittest.TestCase):
    def test_C7_all_clients_including_after_500(self):
        realm = RealmModel(502)
        with contextlib.redirect_stdout(io.StringIO()):
            rs.no_password_grant(realm)
        self.assertTrue(all(not c['directAccessGrantsEnabled'] for c in realm.clients))
        self.assertTrue(realm.clients[-1]['serviceAccountsEnabled'])
        self.assertTrue(all(c['secret'] == SECRET and c['attributes'] == {'keep': 'unchanged'} for c in realm.clients))
        count = len(realm.writes)
        with contextlib.redirect_stdout(io.StringIO()):
            rs.no_password_grant(realm)
        self.assertEqual(len(realm.writes), count)

    def test_C7_small_migration_roles_order_idempotency_and_no_secret_output(self):
        realm = RealmModel()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rs.no_password_grant(realm)
            rs.service_roles(realm, 'audience')
            count = len(realm.writes)
            rs.no_password_grant(realm)
            rs.service_roles(realm, 'audience')
        self.assertTrue(realm.sa and realm.role)
        self.assertEqual(len(realm.writes), count)
        self.assertNotIn(SECRET, out.getvalue())
        self.assertEqual(realm.clients[0]['secret'], SECRET)
        self.assertEqual(realm.writes[0][0], 'PUT')
        self.assertEqual(realm.writes[0][2]['attributes'], {'keep': 'unchanged'})

    def test_C7_old_bot_is_retired_when_test_user_creation_is_off(self):
        realm = RealmModel()
        env = {'CMAPI_REALM_ISSUER': 'https://issuer.example/realms/cmapi', 'CMAPI_REALM_ADMIN_CLIENT_SECRET': SECRET,
               'CMAPI_REALM_TEST_USERS': 'false'}
        with patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(io.StringIO()):
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(rs, 'Realm', return_value=realm))
                for name in ('wait_for_realm', 'user_profile', 'service_roles', 'groups', 'ldap'):
                    stack.enter_context(patch.object(rs, name, return_value={}))
                rs.main([])
        self.assertIsNone(realm.bot, 'enabled bot-user and its password survive; browser authentication is still available')


if __name__ == '__main__':
    unittest.main()

"""Render only; prove the realm import explicitly overrides Keycloak's generated admin-cli."""
import os
from pathlib import Path
import shutil
import subprocess
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[3]
CHART = Path(os.environ.get('REVIEW_CHART', ROOT / 'deploy/helm/cmapi'))


@unittest.skipIf(shutil.which('helm') is None, 'helm')
class HelmAdminCliTests(unittest.TestCase):
    def test_import_disables_generated_password_client(self):
        args = ['helm', 'template', 'cmapi', str(CHART), '-n', 'cmapi', '-f', str(ROOT / 'deploy/environments/crc.yaml'),
                '--set', 'cmapi.digest=sha256:' + 'a' * 64, '--set', 'cmapi_portal.digest=sha256:' + 'b' * 64, '--set', 'trustedCA.certificates=']
        result = subprocess.run(args, capture_output=True, text=True, check=True)
        docs = list(yaml.safe_load_all(result.stdout))
        realm = next(d for d in docs if d and d['kind'] == 'KeycloakRealmImport')['spec']['realm']
        admin = next((c for c in realm['clients'] if c['clientId'] == 'admin-cli'), None)
        self.assertIsNotNone(admin, 'Keycloak creates enabled admin-cli with direct grants unless the import overrides it')
        self.assertIs(admin['enabled'], False)
        self.assertIs(admin['directAccessGrantsEnabled'], False)
        # No client of the chart's realm takes the password grant, and each one says so itself (#181).
        self.assertEqual([c['clientId'] for c in realm['clients'] if c.get('directAccessGrantsEnabled') is not False], [])


if __name__ == '__main__':
    unittest.main()

# Trusting CRC's CAs on a MacBook, for local development

For local development and testing against CRC on this Mac (`olas-MacBook-Pro.local`). Chrome refuses CRC's sites until macOS trusts the two CAs below, and clicking through the warning would be TLS verification off. Run it yourself, because macOS asks for your password.

Trust these only while you need them. Each CA can issue a certificate for any site, and both keys live on a test cluster. This is never for a production machine or production CAs.

| CA | Signs | Expires | SHA-1 fingerprint |
|---|---|---|---|
| `LDAP Enterprise Root CA` | `keycloak.apps-crc.testing` (passthrough Route) | 2036-10-25 | `58E4A0F4B51C06119EA25526330BEA85885B0FD8` |
| `ingress-operator@1789448506` | `*.apps-crc.testing` (edge Routes) | 2028-09-14 | `C016211CBBB5CD072C3FFAC433221C38D1374E05` |

Read from CRC on 2026-11-06. A CRC that was recreated has new CAs, so the commands stop on the fingerprint. Check where the new certificate came from before putting its fingerprint here.

## Trust them

Needs `oc` logged in to CRC. Run in zsh:

```zsh
CA_DIR=~/.cmapi-crc-ca
mkdir -m 700 -p "$CA_DIR"
oc get secret keycloak-tls -n keycloak -o 'jsonpath={.data.ca\.crt}' | base64 -d > "$CA_DIR/keycloak-ca.pem"
# The ingress bundle holds the *.apps-crc.testing site certificate first and the CA second. Only the CA is trusted.
oc get cm default-ingress-cert -n openshift-config-managed -o 'jsonpath={.data.ca-bundle\.crt}' \
  | awk '/BEGIN CERTIFICATE/{n++} n==2' > "$CA_DIR/ingress-ca.pem"

for pair in keycloak-ca:58E4A0F4B51C06119EA25526330BEA85885B0FD8 ingress-ca:C016211CBBB5CD072C3FFAC433221C38D1374E05; do
  f="$CA_DIR/${pair%%:*}.pem"; want=${pair##*:}
  got=$(openssl x509 -in "$f" -noout -fingerprint -sha1 | cut -d= -f2 | tr -d :)
  if [[ $got == $want ]]; then
    security add-trusted-cert -r trustRoot -p ssl -k ~/Library/Keychains/login.keychain-db "$f" && echo "trusted $f"
  else
    echo "STOP $f: got $got"
  fi
done
```

You should see two `trusted` lines. A `STOP` line means that certificate was not trusted.

## Check it

Restart Chrome if it was open, then open these. Neither should show a certificate error:

- `https://keycloak.apps-crc.testing/realms/master`
- `https://console-openshift-console.apps-crc.testing`

**Keycloak's certificate may still be refused.** It has no Extended Key Usage, so macOS's own check rejects it even with its CA as the anchor (`security verify-cert -p ssl`: `Invalid Extended Key Usage for policy`), while the ingress certificate passes. Chrome has its own verifier, and its result is not measured yet. If Chrome refuses it, the fix is reissuing `keycloak-tls` on the shared Keycloak, which is the owner's decision.

## Tools other than a browser

Command-line tools don't need the keychain. Give them the CA file:

```zsh
curl --cacert ~/.cmapi-crc-ca/keycloak-ca.pem https://keycloak.apps-crc.testing/realms/master
curl --cacert ~/.cmapi-crc-ca/ingress-ca.pem https://console-openshift-console.apps-crc.testing/
```

Measured on this Mac: both answer 200, and the wrong CA fails with curl error 60. Never use `-k`. `deploy/crc-trust.sh --mac-ca <file>` writes one bundle for scripts, which also contains the site certificate, so use it with `--cacert` and never add it to the keychain.

## Remove them

When you finish testing:

```zsh
CA_DIR=~/.cmapi-crc-ca
security remove-trusted-cert "$CA_DIR/keycloak-ca.pem"
security remove-trusted-cert "$CA_DIR/ingress-ca.pem"
security delete-certificate -Z 58E4A0F4B51C06119EA25526330BEA85885B0FD8 ~/Library/Keychains/login.keychain-db
security delete-certificate -Z C016211CBBB5CD072C3FFAC433221C38D1374E05 ~/Library/Keychains/login.keychain-db
```

## What has been tested

The download, the fingerprint check and the `curl` commands were run on this Mac. The `security add-trusted-cert`, `remove-trusted-cert` and `delete-certificate` lines have not, because they change the keychain: this file is the first time they get used.

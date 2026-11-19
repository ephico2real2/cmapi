{{/*
Names, labels and the few computed values the templates share.
*/}}
{{- define "cmapi.name" -}}{{ .Release.Name }}{{- end -}}

{{- define "cmapi.labels" -}}
app.kubernetes.io/part-of: cmapi
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
cmapi.net/instance: {{ .Values.instance.name }}
{{- end -}}

{{- define "cmapi.component" -}}
app.kubernetes.io/name: {{ include "cmapi.name" . }}-{{ .component }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/* An image reference, always by digest (deploy/images.lock.yaml). A tag can move under a release; the tag in the lock file is a record. */}}
{{- define "cmapi.image" -}}
{{- $img := index .Values .key -}}
{{- $digest := required (printf "%s.digest is required: deploy by digest from deploy/images.lock.yaml" .key) $img.digest -}}
{{- if not (regexMatch "^sha256:[a-f0-9]{64}$" $digest) -}}{{- fail (printf "%s.digest is not a sha256 digest: %s" .key $digest) -}}{{- end -}}
{{ $img.repository }}@{{ $digest }}
{{- end -}}

{{/* The database URL source: CNPG's generated app Secret, or the site's own. */}}
{{- define "cmapi.dbSecret" -}}
{{- if .Values.database.cnpg.enabled -}}{{ .Values.database.cnpg.name }}-app{{- else -}}{{ required "database.existingSecret is required when CNPG is off" .Values.database.existingSecret }}{{- end -}}
{{- end -}}

{{- define "cmapi.podSecurityContext" -}}
runAsNonRoot: {{ .Values.securityContext.runAsNonRoot }}
seccompProfile: {{ toYaml .Values.securityContext.seccompProfile | nindent 2 }}
{{- if .Values.securityContext.runAsUser }}
runAsUser: {{ .Values.securityContext.runAsUser }}
{{- end }}
{{- end -}}

{{/* Environment shared by the api, the worker and the jobs. */}}
{{- define "cmapi.commonEnv" -}}
- name: CMAPI_CONFIG_DIR
  value: /etc/cmapi/config
- name: CMAPI_POLICIES_DIR
  value: /etc/cmapi/policies
- name: CMAPI_IMPORTS_NAMESPACE
  value: {{ .Values.imports.namespace | quote }}
- name: CMAPI_GIT_PROVIDER
  value: {{ .Values.git.provider | quote }}
- name: CMAPI_GIT_URL
  value: {{ .Values.git.apiUrl | quote }}
- name: CMAPI_GIT_DEFAULT_BRANCH
  value: {{ .Values.git.defaultBranch | quote }}
- name: CMAPI_GIT_TOKEN
  valueFrom: {secretKeyRef: {name: {{ .Values.git.credentialSecret }}, key: token, optional: true}}
- name: CMAPI_GIT_USER
  valueFrom: {secretKeyRef: {name: {{ .Values.git.credentialSecret }}, key: username, optional: true}}
- name: CMAPI_GIT_PASSWORD
  valueFrom: {secretKeyRef: {name: {{ .Values.git.credentialSecret }}, key: password, optional: true}}
- name: CMAPI_DATABASE_URL
  valueFrom: {secretKeyRef: {name: {{ include "cmapi.dbSecret" . }}, key: uri}}
- name: CMAPI_CURSOR_KEY
  valueFrom: {secretKeyRef: {name: {{ include "cmapi.name" . }}-keys, key: cursorKey}}
- name: CMAPI_LINK_KEY
  valueFrom: {secretKeyRef: {name: {{ include "cmapi.name" . }}-keys, key: linkKey}}
- name: CMAPI_DIRECTORY_CLIENT_SECRET
  valueFrom: {secretKeyRef: {name: {{ .Values.auth.directorySecret }}, key: directoryClientSecret, optional: true}}
{{- if .Values.auth.jwksUrl }}
- name: CMAPI_OIDC_JWKS_URL
  value: {{ .Values.auth.jwksUrl | quote }}
{{- end }}
{{- if .Values.auth.adminUrl }}
- name: CMAPI_KEYCLOAK_ADMIN_URL
  value: {{ .Values.auth.adminUrl | quote }}
{{- end }}
{{- if or .Values.trustedCA.certificates .Values.trustedCA.injected.enabled }}
- name: CMAPI_CA_BUNDLE
  value: /etc/cmapi/ca/ca-bundle.crt
- name: REQUESTS_CA_BUNDLE
  value: /etc/cmapi/ca/ca-bundle.crt
- name: SSL_CERT_FILE
  value: /etc/cmapi/ca/ca-bundle.crt
{{- end }}
{{- with include "cmapi.trustedCAFile" . }}
# The trust of a cluster with no caData, after the image's system store (#434). Colon-separated, like SSL_CERT_FILE.
- name: CMAPI_TRUSTED_CA_FILE
  value: {{ . | quote }}
{{- end }}
{{- end -}}

{{/* The bundles of CMAPI_TRUSTED_CA_FILE, colon-joined: the injected one, then the operator's. Empty when neither is on. */}}
{{- define "cmapi.trustedCAFile" -}}
{{- $files := list -}}
{{- if .Values.trustedCA.injected.enabled -}}
{{- $files = append $files "/etc/cmapi/trusted-ca/injected/ca-bundle.crt" -}}
{{- end -}}
{{- if .Values.trustedCA.existingConfigMap.enabled -}}
{{- $files = append $files (printf "/etc/cmapi/trusted-ca/operator/%s" .Values.trustedCA.existingConfigMap.key) -}}
{{- end -}}
{{- join ":" $files -}}
{{- end -}}

{{- define "cmapi.commonVolumeMounts" -}}
- name: config
  mountPath: /etc/cmapi/config
  readOnly: true
{{- if or .Values.trustedCA.certificates .Values.trustedCA.injected.enabled }}
- name: trust
  mountPath: /etc/cmapi/ca
  readOnly: true
{{- end }}
{{- if .Values.trustedCA.injected.enabled }}
- name: trusted-ca-injected
  mountPath: /etc/cmapi/trusted-ca/injected
  readOnly: true
{{- end }}
{{- if .Values.trustedCA.existingConfigMap.enabled }}
- name: trusted-ca-operator
  mountPath: /etc/cmapi/trusted-ca/operator
  readOnly: true
{{- end }}
{{- end -}}

{{- define "cmapi.commonVolumes" -}}
- name: config
  configMap:
    name: {{ include "cmapi.name" . }}-config
{{- if or .Values.trustedCA.certificates .Values.trustedCA.injected.enabled }}
- name: trust
  projected:
    sources:
      - configMap:
          # trustedCA.certificates; else the injected bundle, which Keycloak, Git and the database trusted before #434.
          name: {{ include "cmapi.name" . }}-{{ ternary "trust" "trusted-ca" (not (empty .Values.trustedCA.certificates)) }}
          items: [{key: ca-bundle.crt, path: ca-bundle.crt}]
{{- end }}
{{- if .Values.trustedCA.injected.enabled }}
- name: trusted-ca-injected
  configMap:
    name: {{ include "cmapi.name" . }}-trusted-ca
    # Optional: OpenShift fills it after the pods start; a bundle that is not there yet is skipped and read at the next check.
    optional: true
{{- end }}
{{- if .Values.trustedCA.existingConfigMap.enabled }}
- name: trusted-ca-operator
  configMap:
    # Not optional: a ConfigMap you named that is not there stops the pods rather than start without the CA you asked for.
    name: {{ .Values.trustedCA.existingConfigMap.name }}
    items: [{key: {{ .Values.trustedCA.existingConfigMap.key }}, path: {{ .Values.trustedCA.existingConfigMap.key }}}]
{{- end }}
{{- end -}}

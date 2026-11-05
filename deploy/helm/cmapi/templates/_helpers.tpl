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

{{/* An image reference: by digest when the lock file gives one, else by tag. */}}
{{- define "cmapi.image" -}}
{{- $img := index .Values .key -}}
{{- if $img.digest -}}{{ $img.repository }}@{{ $img.digest }}{{- else -}}{{ $img.repository }}:{{ required (printf "%s: a tag or a digest is required (deploy/images.lock.yaml)" .key) $img.tag }}{{- end -}}
{{- end -}}

{{/* The database URL source: CNPG's generated app Secret, or the site's own. */}}
{{- define "cmapi.dbSecret" -}}
{{- if .Values.database.cnpg.enabled -}}{{ .Values.database.cnpg.name }}-app{{- else -}}{{ required "database.existingSecret is required when CNPG is off" .Values.database.existingSecret }}{{- end -}}
{{- end -}}

{{- define "cmapi.apiHost" -}}
{{- if eq .Values.exposure "Ingress" -}}{{ required "ingress.api.host is required with Ingress exposure" .Values.ingress.api.host }}{{- else -}}{{ .Values.route.api.host }}{{- end -}}
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
          name: {{ include "cmapi.name" . }}-trust
          items: [{key: ca-bundle.crt, path: ca-bundle.crt}]
{{- end }}
{{- end -}}

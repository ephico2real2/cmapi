{{- define "cmapi-git.rootUrl" -}}
{{- if .Values.rootUrl -}}{{ .Values.rootUrl }}{{- else if eq .Values.exposure "Ingress" -}}http://{{ .Values.ingress.host }}/{{- else -}}http://{{ .Release.Name }}-gitea.{{ .Release.Namespace }}.svc:3000/{{- end -}}
{{- end -}}
{{- define "cmapi-git.domain" -}}
{{- $u := include "cmapi-git.rootUrl" . -}}
{{- $u = regexReplaceAll "^https?://" $u "" -}}
{{- regexReplaceAll "[:/].*$" $u "" -}}
{{- end -}}

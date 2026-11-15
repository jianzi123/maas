{{- define "maas.name" -}}
{{- printf "%s-maas" .Release.Name | trunc 50 | trimSuffix "-" -}}
{{- end -}}
{{- define "maas.labels" -}}
app.kubernetes.io/part-of: maas
app.kubernetes.io/instance: {{ .Release.Name | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service | quote }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
{{- end -}}
{{- define "maas.selector" -}}
app.kubernetes.io/instance: {{ .root.Release.Name | quote }}
app.kubernetes.io/name: {{ include "maas.name" .root }}-{{ .component }}
{{- end -}}
{{/*
Removes all non-URL compliant special characters from the input, and trims any
remaining special characters at the end of the name.
*/}}
{{- define "sanitizeName" -}}
{{- $sanitizedName := regexReplaceAll "[^a-zA-Z0-9_.-]" (. | trunc 63) "_" -}}
{{- regexReplaceAll "\\W+$" $sanitizedName "" -}}
{{- end -}}

{{/*
Expand the name of the chart.
*/}}
{{- define "app.name" -}}
{{- include "sanitizeName" (default .Chart.Name .Values.nameOverride) }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "app.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- include "sanitizeName" .Values.fullnameOverride  }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- include "sanitizeName" .Release.Name }}
{{- else }}
{{- include "sanitizeName" (printf "%s-%s" .Release.Name $name) }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "app.chart" -}}
{{- include "sanitizeName" (printf "%s-%s" .Chart.Name .Chart.Version) }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "app.labels" -}}
helm.sh/chart: {{ include "app.chart" . }}
{{ include "app.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "app.selectorLabels" -}}
app.kubernetes.io/name: {{ include "app.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "app.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "app.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/* PodDisruptionBudget helpers */}}
{{- define "app.podDisruptionBudget" -}}
minAvailable: {{ default "50%" .Values.podDisruptionBudget.minUnavailable }}
{{- if .Values.podDisruptionBudget.maxUnavailable }}
maxUnavailable: {{ .Values.podDisruptionBudget.maxUnavailable }}
{{- end }}
{{- end }}

{{- define "app.podDisruptionBudget.deploy" -}}
  {{- and .Values.podDisruptionBudget (or .Values.autoscaling.enabled (gt (int .Values.replicaCount) 1)) }}
{{- end -}}

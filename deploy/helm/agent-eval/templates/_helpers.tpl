{{- define "aep.name" -}}{{ .Release.Name }}{{- end -}}

{{- define "aep.labels" -}}
app.kubernetes.io/part-of: agent-eval
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "aep.databaseUrl" -}}
{{- if .Values.postgres.enabled -}}
postgresql+psycopg://{{ .Values.postgres.user }}:{{ .Values.postgres.password }}@{{ include "aep.name" . }}-postgres:5432/{{ .Values.postgres.database }}
{{- else -}}
{{ required "postgres.externalUrl is required when postgres.enabled=false" .Values.postgres.externalUrl }}
{{- end -}}
{{- end -}}

{{- define "aep.redisUrl" -}}
{{- if .Values.redis.enabled -}}
redis://{{ include "aep.name" . }}-redis:6379/0
{{- else -}}
{{ required "redis.externalUrl is required when redis.enabled=false" .Values.redis.externalUrl }}
{{- end -}}
{{- end -}}

{{- define "aep.image" -}}{{ .Values.image.repository }}:{{ .Values.image.tag }}{{- end -}}

{{/* Env shared by the API and dispatcher. */}}
{{- define "aep.env" -}}
- name: AEP_DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "aep.name" . }}-secrets
      key: database-url
- name: AEP_REDIS_URL
  value: {{ include "aep.redisUrl" . | quote }}
- name: AEP_NAMESPACE
  valueFrom:
    fieldRef:
      fieldPath: metadata.namespace
- name: AEP_TRIAL_IMAGE
  value: {{ include "aep.image" . | quote }}
- name: AEP_API_URL
  value: "http://{{ include "aep.name" . }}-api:{{ .Values.api.port }}"
- name: AEP_MAX_CONCURRENCY
  value: {{ .Values.dispatcher.maxConcurrency | quote }}
- name: AEP_TRIAL_CPU_LIMIT
  value: {{ .Values.trial.cpuLimit | quote }}
- name: AEP_TRIAL_MEMORY_LIMIT
  value: {{ .Values.trial.memoryLimit | quote }}
- name: AEP_TRIAL_DEADLINE_SECONDS
  value: {{ .Values.trial.deadlineSeconds | quote }}
{{- end -}}

{{- define "aep.containerSecurity" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
{{- end -}}

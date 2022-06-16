# Helm Chart for [changedetection.io](https://github.com/dgtlmoon/changedetection.io#changedetectionio)

```bash
helm repo add chris2k20 https://chris2k20.github.io/helm-charts/
helm install changedetectionio chris2k20/changedetectionio \
  --namespace change-example-com \
  --create-namespace \
  --set ingress.enabled=true
```

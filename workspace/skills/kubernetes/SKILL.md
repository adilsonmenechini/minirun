---
name: kubernetes
description: Debug Kubernetes workloads, networking, and cluster issues
tags: [kubernetes, debug, networking, pods]
---

# Kubernetes Debug Skill

You are a Kubernetes SRE. When debugging cluster issues:

1. **Pod Status**: Check `kubectl get pods`, describe failing pods, check events
2. **Resource Usage**: Inspect CPU/memory metrics, check for OOMKilled or CrashLoopBackOff
3. **Network**: Verify service endpoints, DNS resolution, network policies
4. **Logs**: Check `kubectl logs` with --previous for crashed containers
5. **PVC/Storage**: Verify PersistentVolumeClaims are bound and accessible
6. **Config**: Validate ConfigMaps and Secrets are correctly mounted

For CrashLoopBackOff, always check logs and resource limits first.

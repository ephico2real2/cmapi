# #751, delivery.mode gitops: the coordinator's assessment before the design

Written 2026-11-27, at the owner's request ("Redirect your output into a file first"). It is the input to the design in this
folder's README, and is not the design itself.

## The owner's decision

- "It shouldn't matter what apply the rendered yaml."
- Asked whether to build a deliverer-agnostic mode next: "Build gitops mode now".
- Asked whether the design choice makes sense, after the three cases below were named: "Yes".

## Why it makes sense

- **The contract is Git, and the proof is the cluster.** cmapi already ends every request with a read of the cluster, not a
  deliverer's report (`confirmed_by_read`, `core/sync.py`). Making that read the only proof is a small change.
- **It keeps cmapi out of the deliverer's business.** Argo CD, Flux, ACM or a pipeline can each apply the folder, with no code
  in cmapi for any of them, and a site can change deliverer without changing cmapi.
- **It is stricter than trusting a status.** A deliverer's "synced" describes its own view of its own scope. cmapi's read
  checks exactly what the request approved: these labels, these quotas, these LimitRanges, and this object gone.
- **It needs no new permissions.** The reader already reads Namespaces, ResourceQuotas and LimitRanges.

## Three cases the design must handle

1. **"Not applied yet" against "applied and failed".** With only a read, cmapi sees "does not match yet" until the timeout.
   It cannot tell a deliverer that has not run from one whose apply was refused, for example by an admission webhook.
   - When the deliverer's status is readable (Argo CD Application, Flux Kustomization), it is optional signal: cmapi shows
     the deliverer's error.
   - Without it, the timeout's `sync_failed` lists the exact differences between the plan and the read.
2. **A newer request superseding an older one.** Two requests on the same namespace can merge close together, so the older
   request's read sees the newer values and never matches.
   - Compare against the folder as of the request's merged commit.
   - Treat "superseded by a later approved request for the same namespace" as done, recorded with that request's ID, never
     as failed.
3. **Deletes when the deliverer does not prune.** Some setups never delete automatically, for example Argo CD without
   automated prune, so waiting for absence would only time out.
   - Treat it as "awaiting prune", with a notice to an operator, as `apply` mode already does with
     `POST /admin/prune:confirm`. It is not a failure.

## Also in scope (from #751)

- The full-plan read in every mode: the Namespace's governed labels and annotations (not the server-owned keys, not
  `liveOnlyKeys`), every ResourceQuota's hard values, every LimitRange's limits, and the absence of each removed object.
  - Quantities compare by value (`qty`), not by spelling.
  - This also closes #26's deferred B4.
- `argocd` and `apply` keep working. The design decides, with its reasons, whether `argocd` becomes `gitops` plus the
  optional Argo CD signal, keeping the configuration compatible.

## To verify against primary sources before the design is written

Fetch and quote each source, with the date read. None of the following is assumed:
- Kubernetes server-side apply and field ownership;
- the Argo CD Application sync and health status, and its prune policy;
- the Flux Kustomization `Ready` condition and its prune behaviour.

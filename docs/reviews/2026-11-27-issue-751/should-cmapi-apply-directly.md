# Should cmapi apply cmapi-cluster-configs directly?

The coordinator's answer of 2026-11-27 to the owner's question: "So should cmapi apply that the cmapi-cluster-configs
directly?" The owner asked for the answer to be kept in a file. It is an input to #751's design, next to
`coordinator-assessment.md`.

## Answer: not by default

cmapi may apply as **one deliverer among several**, and already does on CRC (`delivery.mode: apply`). A GitOps controller
should be the normal path (`delivery.mode: gitops`, #751).

## Why not by default

1. **The approver should not also hold the keys.** If cmapi applies, the hub needs write access on every managed cluster:
   creating Namespaces, ResourceQuotas and LimitRanges. A compromise of cmapi, or a bug in it, could then change every
   cluster. With a GitOps controller, cmapi only writes Git and reads clusters, and each cluster's controller holds its
   write access locally.
2. **One apply does not keep things correct.** In `apply` mode cmapi applies once, per request. No job re-applies when
   someone changes a quota by hand: `git_reconcile` (`jobs/git_reconcile.py`, every 900 s) only cleans up the PRs and
   branches that a crashed worker left. A GitOps controller re-applies continuously, so drift is repaired without a new
   request.
3. **Sites already run a deliverer.** OpenShift clusters usually have OpenShift GitOps (Argo CD), or ACM. If cmapi did the
   same job, it would duplicate them and split ownership of the same objects.
4. **It contradicts the owner's rule from the other direction.** "It shouldn't matter what apply the rendered yaml" means
   cmapi does not care who applies. Making cmapi the applier ties delivery to cmapi instead of to Argo CD.

## Where cmapi applying directly is right

On a cluster with no deliverer, such as CRC today. `apply` mode is built to be safe there (`core/sync.py`):
- **A separate identity:** a deliverer identity, not the reader.
- **Reviewed RBAC:** it is held to the chart's reviewed RBAC (`deploy/manifests/environments/crc/deliverer/`, kept equal by
  `test_crc_deliverer_is_the_charts`).
- **Managed namespaces only:** it refuses a namespace that exists and that cmapi does not manage.
- **Apply before merge:** Git never shows something that failed to apply.
- **Documented as an exception:** "the only cluster write cmapi ever makes, and it is documented as a deployment choice,
  not the design's default".

## The plan

- **`gitops`**, the normal mode (#751): any controller applies, and cmapi proves the result by a full read of the
  approved plan.
- **`apply`**, for labs and clusters with no deliverer, tightly scoped.
- **No GitHub Actions applying:** that would put cluster credentials on GitHub's runners. Actions in `cmapi-cluster-configs`
  only validate (kubeconform, kyverno).

## If the owner wants cmapi to apply everywhere

Two additions come first, and they are a larger design change, for the owner to decide:
- a continuous drift-repair job;
- a deliverer identity for each cluster.

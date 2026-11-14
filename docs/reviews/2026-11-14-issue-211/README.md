# Issue #211: values beyond the tier on the custom tier, with approval as the gate

OB1 (Fable 5.2) wrote this record on 2026-11-14, before the code. It gives the decision, the research and the options that were not taken. The owner's two decisions of 2026-11-13 are in #211: approval is the gate of a capability, and each value beyond the tier needs an extra approval.

## The decision

1. **A custom-tier request can change the container limits.** `NamespaceCreate` and `NamespacePatch` take an optional `limitRange` object. A key that is left out keeps the value of the tier.
2. **A custom-tier request can also change the four quota keys that the catalog fixed until now.** They are `persistentvolumeclaims`, `requests.storage`, `services.loadbalancers` and `services.nodeports`. The request sends them in `quota`, with the three sizable keys.
3. **The catalog names each key that a request can change.** `tiers.yaml` has a new list, `overridable`. A limit key has the form `limitRange.<kind>.<part>.<resource>`, for example `limitRange.container.max.cpu`. A quota key has its Kubernetes name. Each overridable key has a `max` in `custom`, for each environment, and it can have a `min` and a `step`. The three sizable keys stay as they are: a custom request must send each one.
4. **cmapi refuses only a value that is not valid.** The refusals are in the table "What is not valid". Each other value goes to the approval rules.
5. **A value that differs from the tier is "beyond the tier".** The planner gives three facts to `approval-rules.yaml`: `beyondTier` (true or false), `beyondTierKeys` (the list of keys) and `networkExposure` (true when the request raises `services.loadbalancers` or `services.nodeports`). The default rules add one approver of `approver-platform` for `beyondTier`, and one more for `networkExposure`. These approvers are added to the approvers of the environment's rule.
6. **Auto-approval does not cover a request that is beyond the tier.** A policy covers it only if its `match` has `beyondTier: true`. The guard has the name `beyond-tier`. It does not depend on the thresholds, so an instance that removes the threshold does not open auto-approval by accident.
7. **The plan and the dry run name the keys and the extra approval.** `PlanView.beyondTier` and `ChangeRequest.beyondTier` list each key with the value of the tier and the requested value, and each approval that the beyond-tier rules added.
8. **The rendered object records its own overrides.** `limitrange.yaml` and `resourcequota.yaml` get the annotation `cmapi.net/beyond-tier` with the keys, for example `limitRange.container.max.cpu,limitRange.container.max.memory`. The object already has `cmapi.net/request-id`, the request that last changed it. A later change of the namespace reads the annotation and keeps the approved values. A generated policy (#212) can read the same annotation.
9. **A later change asks for the extra approval only for a new value.** A change of a label on a namespace that has approved overrides is not beyond the tier again. `beyondTierKeys` holds only the keys whose value differs from the tier and from the value in Git.

## What is not valid

Each refusal is 422 `policy-violation` with an item code in `errors[].code`. This is the form of each tier refusal today (`docs/02`, "Tiers"), so a client reads one form. #211 asked for a registered problem for each refusal: `policy-violation` is the registered problem, and the item codes are in `docs/02`.

| Item code | When |
|---|---|
| `limits-with-named-tier` | `limitRange` is sent with a tier that is not custom |
| `limit-key-not-overridable` | A limit key is not in `overridable` |
| `quota-key-not-sizable` (existing) | A quota key is not in `sizable` and not in `overridable` |
| `custom-out-of-bounds` (existing) | A value is below `min`, above `max` or off its `step`; each item has the key and its bounds |
| `limit-order-invalid` | For a container resource, the values are not in the order min, defaultRequest, default, max |
| `limit-exceeds-quota` | The container `max` of CPU or memory is above `requests.cpu` or `requests.memory` of the same request |

Kubernetes does not make the two last checks for cmapi. "A LimitRange does **not** check the consistency of the default values it applies. This means that a default value for the *limit* that is set by LimitRange may be less than the *request* value specified for the container in the spec that a client submits to the API server. If that happens, the final Pod will not be schedulable." (LimitRange concept page). The catalog has the same two checks for each named tier, so a custom value gets the check that a tier value gets.

## The fixed quota keys: research and recommendation

#211 asked for research, not a decision by the owner: does "approval is the gate" open the quota keys that the custom tier fixes? The owner's rule of 2026-11-13 is "we shouldn't block a feature". The rule for this run adds: network exposure gets a recorded recommendation before it opens. This section is that record.

### Storage: `persistentvolumeclaims` and `requests.storage`

They are capacity, as CPU and memory are. Kubernetes describes them as "the sum of storage requests cannot exceed this value" and "the total number of PersistentVolumeClaims that can exist in the namespace" (Resource Quotas). A higher value uses more of a shared storage backend, and it opens no path into the cluster. **Decision: open, with a `max` for each environment, and the beyond-tier approval.** cmapi's capacity check reads CPU and memory only, so the platform approver is the check of storage capacity. The approval slot gives the reason.

### Network: `services.loadbalancers` and `services.nodeports`

What each one does:

- A NodePort opens one port on each node. "Each node proxies that port (the same port number on every Node) into your Service." "You'll be able to contact the `type: NodePort` Service, from outside the cluster, by connecting to any node" (Kubernetes, Service). OpenShift: "This configuration opens a specific port on every node in the cluster, allowing external traffic to reach your workloads by using an IP address of any node", and "The administrator must ensure the external IP addresses are routed to the nodes."
- A LoadBalancer Service asks the infrastructure for a load balancer and an address. Kyverno's policy library gives the reason to restrict it: "Especially in cloud provider environments, a Service having type LoadBalancer will cause the provider to respond by creating a load balancer somewhere in the customer account. This adds cost and complexity to a deployment. Without restricting this ability, users may easily overrun established budgets and security practices set by the organization."
- Kyverno's library also restricts NodePort: "NodePort services expose applications on a static port on each node, which can pose security risks and complicate network management."
- `services.nodeports` counts "the total number of `NodePorts` allocated to Services of type `NodePort` or `LoadBalancer`". So a LoadBalancer Service also uses the NodePort quota, unless the Service sets `allocateLoadBalancerNodePorts: false`. A request for a load balancer must ask for both keys, or the team sets that field.
- A quota is a count. It does not say which port, which source address or which protocol. "Quotas cannot protect against all kinds of resource sharing, such as network traffic." (Kubernetes, Multi-tenancy).

**The view of a platform team, from these sources.** The default stays 0 for each tier: HTTP and HTTPS go through the Route and its ingress controller, which give TLS, a host name and one audited path. A NodePort or a load balancer is an exception for a protocol that the ingress controller does not carry. An exception needs a person who knows the network: the firewall in front of the nodes, the address pool of the load balancer, and the NetworkPolicy of the namespace.

**Recommendation, and the decision under the owner's rule: open both keys, as an exception with its own approval.**

1. The default of each tier stays `"0"`. Only a custom-tier request can ask for more.
2. Each environment has a low `max` in the catalog. The reference catalog has 2 load balancers and 10 NodePorts. A higher value is not valid; the platform team raises the bound by a reviewed change of `tiers.yaml`.
3. A request that raises one of the two keys has the fact `networkExposure`. The default rules add one approver of `approver-platform` for it, on top of the beyond-tier approver. So such a request in `dev` needs three approvals from `approver-platform`: the create, the beyond-tier value and the network exposure. An instance can name a network or security group in that rule.
4. Auto-approval never covers it (decision 6).
5. Not built here: a policy on the Service itself (allowed ports, `loadBalancerSourceRanges`, internal load balancers only). The quota opens a count, and the approver decides on the rest by hand. #212 lists the Service among the objects for a generated policy.

An instance that does not want the exception removes the two keys from `overridable`. Then the request is refused with `quota-key-not-sizable`, as today.

## A change of a custom namespace: `PATCH`

`quota` and `limitRange` of a `PATCH` are merged, key by key, over the values that the namespace has in Git. A key that is not sent keeps its value. To go back to the value of the tier, send that value: a value equal to the tier is not an override, and the annotation drops the key. A change from the custom tier to a named tier drops each override, because a named tier takes no `quota` and no `limitRange`.

A value that Git holds was approved. A later change of the catalog does not refuse it: cmapi does not check it against the bounds again, and it stays valid when the catalog no longer names its key as overridable. A new value for that key gets each check.

Before this change, a `PATCH` of a custom namespace was refused each time (#214, BUG-54): the planner sent each key of the rendered quota back as the request's quota. The fix reads only the sizable keys and the keys of the annotation.

## Options that were not taken

| Option | Why not |
|---|---|
| A problem type in `PROBLEMS` for each refusal | Each tier refusal is `policy-violation` with an item code. A second form for the same class of refusal gives a client two parsers |
| A typed `limitRange` model with fixed fields | The catalog decides which keys a request can change. A fixed model moves that decision into code, and `limit-key-not-overridable` could not be reached |
| A fact `limitIncreasePct`, as `quotaIncreasePct` | The bounds of the environment hold the size. The owner's later decision names one fact, `beyondTier`, with its keys. A percentage of a value that starts at 0 (`services.loadbalancers`) has no meaning |
| `null` in a `PATCH` to remove an override | A value equal to the tier does the same with no new type |
| Read the overrides back by a comparison of the file with the tier | The comparison gives a wrong answer after the catalog changes a tier value. The annotation is explicit state, and a person can read it in Git |
| Keep the network keys closed | The owner's rule: do not block a capability. The low bound and the extra approval hold the risk |

## What was not tested

No cluster ran for this change (#157). The LimitRange and ResourceQuota are rendered files; no API server admitted them. kubeconform and the Kyverno CLI are not on this Mac, so the service tests use the stand-in validator, as before.

## Sources

Each was read on 2026-11-14.

- Kubernetes, Limit Ranges: <https://kubernetes.io/docs/concepts/policy/limit-range/> (source `kubernetes/website` at `a96b3ebd1529`).
- Kubernetes, Resource Quotas: <https://kubernetes.io/docs/concepts/policy/resource-quotas/> (the same commit).
- Kubernetes, Service, `type: NodePort`: <https://kubernetes.io/docs/concepts/services-networking/service/#type-nodeport>.
- Kubernetes, Multi-tenancy, "Quotas": <https://kubernetes.io/docs/concepts/security/multi-tenancy/#quotas>.
- OpenShift Container Platform 4.19, "Configuring ingress cluster traffic by using a NodePort" (source `openshift/openshift-docs`, branch `enterprise-4.19` at `3eafc018a1d8`, `modules/nw-using-nodeport.adoc`).
- Kyverno policy library at `85554e1ef32b`: `best-practices-vpol/restrict-node-port/restrict-node-port.yaml` and `other-vpol/restrict-loadbalancer/restrict-loadbalancer.yaml`, <https://github.com/kyverno/policies>.

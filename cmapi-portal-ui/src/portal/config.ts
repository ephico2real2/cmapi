// The portal's runtime settings. The deployment writes config.json beside index.html, so one build serves each instance
// and no issuer, client or API address is compiled into the bundle.

export interface PortalConfig {
  /** The public URL of this instance's API, without a path. */
  apiUrl: string;
  /** The OIDC issuer: the URL of the Keycloak realm. */
  issuer: string;
  /** The portal's public client in that realm. */
  clientId: string;
  /** The name of this instance, for example nonprod. */
  instance: string;
  /** The name of this instance for a sentence, for example Non-production. */
  displayName: string;
  /** The environments that this instance serves. */
  environments: string[];
}

/** config.json is missing or wrong. The portal shows the message and starts nothing. */
export class ConfigError extends Error {}

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

/** An absolute https URL. Plain http is for a developer's own machine only, where no certificate exists. */
function serviceUrl(value: unknown, name: string): string {
  if (typeof value !== "string" || !value) throw new ConfigError(`config.json has no ${name}.`);
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new ConfigError(`config.json: ${name} is not a URL.`);
  }
  const local = url.protocol === "http:" && LOCAL_HOSTS.has(url.hostname);
  if (url.protocol !== "https:" && !local) throw new ConfigError(`config.json: ${name} must be an https URL.`);
  if (url.username || url.password || url.search || url.hash) throw new ConfigError(`config.json: ${name} must have no user, query or fragment.`);
  return value.replace(/\/+$/, "");
}

function text(value: unknown, name: string): string {
  if (typeof value !== "string" || !value.trim()) throw new ConfigError(`config.json has no ${name}.`);
  return value;
}

export function parseConfig(raw: unknown): PortalConfig {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) throw new ConfigError("config.json is not a JSON object.");
  const o = raw as Record<string, unknown>;
  const environments = o.environments ?? [];
  if (!Array.isArray(environments) || environments.some((e) => typeof e !== "string")) throw new ConfigError("config.json: environments must be a list of names.");
  const instance = text(o.instance, "instance");
  const apiUrl = serviceUrl(o.apiUrl, "apiUrl");
  // The API's paths start at the root of its host (/api/v1/...), so a path here would send each call to the wrong place.
  if (new URL(apiUrl).pathname !== "/") throw new ConfigError("config.json: apiUrl must have no path.");
  return {
    apiUrl,
    issuer: serviceUrl(o.issuer, "issuer"),
    clientId: text(o.clientId, "clientId"),
    instance,
    displayName: typeof o.displayName === "string" && o.displayName ? o.displayName : instance,
    environments: environments as string[]
  };
}

export async function loadConfig(signal?: AbortSignal): Promise<PortalConfig> {
  let response: Response;
  try {
    // no-store: a changed ConfigMap must reach the next page load, not a cached copy.
    response = await fetch(new URL("config.json", document.baseURI), { cache: "no-store", credentials: "omit", signal });
  } catch (cause) {
    if (signal?.aborted) throw cause;
    throw new ConfigError("config.json did not load.");
  }
  if (!response.ok) throw new ConfigError(`config.json did not load (HTTP ${response.status}).`);
  let raw: unknown;
  try {
    raw = await response.json();
  } catch {
    throw new ConfigError("config.json is not JSON.");
  }
  return parseConfig(raw);
}

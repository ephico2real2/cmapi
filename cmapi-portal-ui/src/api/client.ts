// The portal's one client of the API. Its paths, parameters and answers are typed from the OpenAPI document.
import createClient from "openapi-fetch";
import type { Client } from "openapi-fetch";
import type { paths } from "./schema.generated";

/** The signed-in session, as the client needs it. The page keeps the tokens; the client only asks for one. */
export interface Session {
  /** The access token now, if the person is signed in. */
  token(): string | undefined;
  /** One renewal with the refresh token. Gives the new access token, or nothing if the issuer refused. */
  renew(): Promise<string | undefined>;
  /** Sends the browser to the issuer to sign in again. */
  signIn(): Promise<void>;
}

export type Api = Client<paths>;

export function createApi(apiUrl: string, session: Session): Api {
  const origin = new URL(apiUrl).origin;
  let renewal: Promise<string | undefined> | undefined;
  // Each call that meets an expired token waits for the same renewal: the realm refuses a refresh token used twice.
  const renewOnce = () => (renewal ??= session.renew().finally(() => { renewal = undefined; }));

  async function authFetch(request: Request): Promise<Response> {
    // The token goes to the API of config.json and to no other origin.
    if (new URL(request.url).origin !== origin) throw new Error(`Refused a call to ${new URL(request.url).origin}: it is not the API.`);
    const send = (token: string) => {
      const attempt = request.clone();
      attempt.headers.set("Authorization", `Bearer ${token}`);
      return fetch(attempt);
    };
    const token = session.token() ?? await renewOnce();
    if (!token) {
      await session.signIn();
      throw new Error("Not signed in.");
    }
    const first = await send(token);
    if (first.status !== 401) return first;
    // 401: the session ended, or the token did. One silent renewal, then the same call again.
    const fresh = await renewOnce();
    if (fresh) {
      const second = await send(fresh);
      if (second.status !== 401) return second;
    }
    await session.signIn();
    return first;
  }

  return createClient<paths>({
    baseUrl: apiUrl,
    fetch: authFetch,
    // Bearer token only: no cookie goes to the API, and a redirect never carries the token to another place.
    credentials: "omit",
    redirect: "error"
  });
}

import { net, protocol } from "electron";
import { pathToFileURL } from "node:url";
import { isAbsolute, normalize, resolve } from "node:path";
import { APP_PROTOCOL } from "@applyocalypse/config";

export const registerArtifactScheme = (): void => {
  protocol.registerSchemesAsPrivileged([
    {
      scheme: APP_PROTOCOL,
      privileges: {
        standard: true,
        secure: true,
        supportFetchAPI: true,
        stream: true
      }
    }
  ]);
};

export type ArtifactProtocolOptions = {
  safeRoots?: string[] | (() => string[]);
  isAllowedPath?: (localPath: string) => boolean;
};

export const artifactUrlForPath = (localPath: string): string =>
  `${APP_PROTOCOL}://artifact?path=${encodeURIComponent(localPath)}`;

const isWithinSafeRoots = (localPath: string, safeRoots: string[]): boolean => {
  if (!isAbsolute(localPath)) {
    return false;
  }

  const normalizedPath = normalize(resolve(localPath)).toLowerCase();
  return safeRoots.some((root) => {
    const normalizedRoot = normalize(resolve(root)).toLowerCase();
    return normalizedPath === normalizedRoot || normalizedPath.startsWith(`${normalizedRoot}\\`) || normalizedPath.startsWith(`${normalizedRoot}/`);
  });
};

const normalizeArtifactPath = (localPath: string): string | null => {
  if (localPath.includes("\0") || !isAbsolute(localPath)) {
    return null;
  }
  return normalize(resolve(localPath));
};

export const resolveAllowedArtifactPath = (
  localPath: string | null,
  { safeRoots, isAllowedPath }: ArtifactProtocolOptions
): string | null => {
  const normalized = localPath ? normalizeArtifactPath(localPath) : null;
  if (!normalized) {
    return null;
  }

  const roots = safeRoots ? (typeof safeRoots === "function" ? safeRoots() : safeRoots) : [];
  const allowedByRoot = isWithinSafeRoots(normalized, roots);
  const allowedByArtifact = isAllowedPath?.(normalized) ?? false;
  return allowedByArtifact || allowedByRoot ? normalized : null;
};

export const registerArtifactProtocolHandler = (options: ArtifactProtocolOptions): void => {
  protocol.handle(APP_PROTOCOL, async (request) => {
    const url = new URL(request.url);
    if (url.hostname !== "artifact") {
      return new Response("Unknown Applyocalypse protocol host", { status: 404 });
    }

    const localPath = url.searchParams.get("path");
    const normalized = resolveAllowedArtifactPath(localPath, options);
    if (!normalized) {
      return new Response("Artifact path is not allowed", { status: 403 });
    }

    return net.fetch(pathToFileURL(normalized).toString());
  });
};

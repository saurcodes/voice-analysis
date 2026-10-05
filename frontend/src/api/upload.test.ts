import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { ApiError } from "./client";
import { uploadAnalysis } from "./upload";

interface FakeProgressEvent {
  lengthComputable: boolean;
  loaded: number;
  total: number;
}

/**
 * Minimal fake XMLHttpRequest: just enough surface for upload.ts (open, setRequestHeader,
 * upload.onprogress, onload, onerror, send) so progress/success/error can be driven by hand
 * from the test, with no real network involved.
 */
class FakeXMLHttpRequest {
  static instances: FakeXMLHttpRequest[] = [];

  method = "";
  url = "";
  requestHeaders: Record<string, string> = {};
  status = 0;
  statusText = "";
  responseText = "";
  sentBody: FormData | null = null;
  aborted = false;
  upload: { onprogress: ((event: FakeProgressEvent) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;

  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }

  setRequestHeader(name: string, value: string) {
    this.requestHeaders[name] = value;
  }

  send(body: FormData) {
    this.sentBody = body;
    FakeXMLHttpRequest.instances.push(this);
  }

  abort() {
    this.aborted = true;
    this.onabort?.();
  }
}

beforeEach(() => {
  FakeXMLHttpRequest.instances = [];
  vi.stubGlobal("XMLHttpRequest", FakeXMLHttpRequest);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function currentXhr(): Promise<FakeXMLHttpRequest> {
  await vi.waitFor(() => expect(FakeXMLHttpRequest.instances).toHaveLength(1));
  return FakeXMLHttpRequest.instances[0];
}

test("sets the bearer header and forwards upload progress", async () => {
  const onProgress = vi.fn();
  const file = new File(["hello"], "clip.wav", { type: "audio/wav", lastModified: 1_700_000_000_000 });

  const promise = uploadAnalysis(file, {}, { getToken: async () => "tok-1", onProgress });
  const xhr = await currentXhr();

  expect(xhr.method).toBe("POST");
  expect(xhr.url).toBe("/api/analyses");
  expect(xhr.requestHeaders.Authorization).toBe("Bearer tok-1");

  xhr.upload.onprogress?.({ lengthComputable: true, loaded: 50, total: 100 });
  expect(onProgress).toHaveBeenCalledWith(50);

  xhr.status = 202;
  xhr.responseText = JSON.stringify({ job_ids: ["j1"] });
  xhr.onload?.();

  await expect(promise).resolves.toEqual({ job_ids: ["j1"] });
});

test("defaults recorded_at from the file's lastModified timestamp", async () => {
  const lastModified = 1_700_000_000_000;
  const file = new File(["hello"], "clip.wav", { lastModified });

  const promise = uploadAnalysis(file, {}, { getToken: async () => "tok" });
  const xhr = await currentXhr();

  expect(xhr.sentBody?.get("recorded_at")).toBe(new Date(lastModified).toISOString());

  xhr.status = 202;
  xhr.responseText = JSON.stringify({ job_ids: ["j1"] });
  xhr.onload?.();
  await promise;
});

test("an explicit recorded_at overrides the file's lastModified default", async () => {
  const file = new File(["hello"], "clip.wav", { lastModified: 1_700_000_000_000 });

  const promise = uploadAnalysis(
    file,
    { recorded_at: "2026-01-01T00:00:00Z" },
    { getToken: async () => "tok" },
  );
  const xhr = await currentXhr();

  expect(xhr.sentBody?.get("recorded_at")).toBe("2026-01-01T00:00:00Z");

  xhr.status = 202;
  xhr.responseText = JSON.stringify({ job_ids: ["j1"] });
  xhr.onload?.();
  await promise;
});

test("maps a 413 {detail} response to ApiError", async () => {
  const file = new File(["hello"], "clip.wav", { lastModified: 1_700_000_000_000 });

  const promise = uploadAnalysis(file, {}, { getToken: async () => "tok" });
  const xhr = await currentXhr();

  xhr.status = 413;
  xhr.statusText = "Payload Too Large";
  xhr.responseText = JSON.stringify({ detail: "file too large" });
  xhr.onload?.();

  await expect(promise).rejects.toBeInstanceOf(ApiError);
  await expect(promise).rejects.toMatchObject({ status: 413, detail: "file too large" });
});

test("aborting the signal aborts the underlying XHR and rejects with a cancelled ApiError", async () => {
  const file = new File(["hello"], "clip.wav", { lastModified: 1_700_000_000_000 });
  const controller = new AbortController();

  const promise = uploadAnalysis(file, {}, { getToken: async () => "tok", signal: controller.signal });
  const xhr = await currentXhr();

  controller.abort();

  expect(xhr.aborted).toBe(true);
  await expect(promise).rejects.toBeInstanceOf(ApiError);
  await expect(promise).rejects.toMatchObject({ status: 0, detail: "upload cancelled" });
});

test("a signal already aborted before the call rejects immediately without opening an XHR", async () => {
  const file = new File(["hello"], "clip.wav", { lastModified: 1_700_000_000_000 });
  const controller = new AbortController();
  controller.abort();

  const promise = uploadAnalysis(file, {}, { getToken: async () => "tok", signal: controller.signal });

  await expect(promise).rejects.toMatchObject({ status: 0, detail: "upload cancelled" });
  expect(FakeXMLHttpRequest.instances).toHaveLength(0);
});

test("aborting the signal while getToken is still pending rejects with the cancel error and never opens an XHR", async () => {
  const file = new File(["hello"], "clip.wav", { lastModified: 1_700_000_000_000 });
  const controller = new AbortController();
  let resolveToken: (token: string) => void = () => {};
  const tokenPromise = new Promise<string>((resolve) => {
    resolveToken = resolve;
  });

  const promise = uploadAnalysis(file, {}, { getToken: () => tokenPromise, signal: controller.signal });

  controller.abort();
  resolveToken("tok");

  await expect(promise).rejects.toBeInstanceOf(ApiError);
  await expect(promise).rejects.toMatchObject({ status: 0, detail: "upload cancelled" });
  expect(FakeXMLHttpRequest.instances).toHaveLength(0);
});

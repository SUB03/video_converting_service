import { useEffect, useState } from "react";
import { apiUrl, jobEventsUrl } from "#/lib/api";

export type StreamStatus = "idle" | "connecting" | "running" | "done" | "error";
export type JobStatus = "pending" | "processing";
export type ConvertedFile = { format: string; url: string };

export type JobEventsState = {
	status: StreamStatus;
	jobStatus?: JobStatus;
	files: ConvertedFile[];
	error?: string;
	log: string[];
};

const initialState: JobEventsState = { status: "idle", files: [], log: [] };

/**
 * Subscribes to the SSE stream of a conversion job.
 * Expects `status` {status}, `done` {files: [{format, url}]} and `error` {message} events.
 */
export function useJobEvents(jobId: string | null): JobEventsState {
	const [state, setState] = useState<JobEventsState>(initialState);

	useEffect(() => {
		if (!jobId) {
			setState(initialState);
			return;
		}

		setState({ ...initialState, status: "connecting" });
		const source = new EventSource(jobEventsUrl(jobId));

		const append = (line: string) =>
			setState((s) => ({
				...s,
				log: [...s.log, `[${new Date().toLocaleTimeString()}] ${line}`],
			}));
		const dataOf = (e: Event) => (e as MessageEvent<string>).data;

		source.onopen = () => {
			setState((s) =>
				s.status === "connecting" ? { ...s, status: "running" } : s,
			);
			append("connected to event stream");
		};

		source.addEventListener("status", (e) => {
			const { status } = JSON.parse(dataOf(e)) as { status: JobStatus };
			setState((s) => ({ ...s, status: "running", jobStatus: status }));
			append(`status ${status}`);
		});

		source.addEventListener("done", (e) => {
			const { files } = JSON.parse(dataOf(e)) as { files: ConvertedFile[] };
			setState((s) => ({
				...s,
				status: "done",
				files: files.map((f) => ({ ...f, url: apiUrl(f.url) })),
			}));
			append(`done: ${files.map((f) => f.format).join(", ")}`);
			source.close();
		});

		// A server-sent "error" event carries data; a connection error doesn't
		source.addEventListener("error", (e) => {
			const data = dataOf(e);
			if (data) {
				const { message } = JSON.parse(data) as { message?: string };
				setState((s) => ({ ...s, status: "error", error: message ?? data }));
				append(`error ${data}`);
				source.close();
			} else if (source.readyState === EventSource.CLOSED) {
				setState((s) => ({
					...s,
					status: "error",
					error: "Event stream closed by server",
				}));
				append("connection closed");
			} else {
				append("connection lost, reconnecting…");
			}
		});

		source.onmessage = (e) => append(`message ${e.data}`);

		return () => source.close();
	}, [jobId]);

	return state;
}

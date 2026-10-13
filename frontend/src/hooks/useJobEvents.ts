import { useEffect, useState } from "react";
import { jobEventsUrl } from "#/lib/api";

export type JobStatus = "idle" | "connecting" | "running" | "done" | "error";

export type JobEventsState = {
	status: JobStatus;
	percent: number;
	url?: string;
	error?: string;
	log: string[];
};

const initialState: JobEventsState = { status: "idle", percent: 0, log: [] };

/**
 * Subscribes to the SSE stream of a conversion job.
 * Expects `progress` {percent}, `done` {url?} and `error` {message} events.
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

		source.addEventListener("progress", (e) => {
			const { percent } = JSON.parse(dataOf(e)) as { percent: number };
			setState((s) => ({ ...s, status: "running", percent }));
			append(`progress ${percent}%`);
		});

		source.addEventListener("done", (e) => {
			const { url } = JSON.parse(dataOf(e)) as { url?: string };
			setState((s) => ({ ...s, status: "done", percent: 100, url }));
			append(`done ${dataOf(e)}`);
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

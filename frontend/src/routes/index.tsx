import { useMutation } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { type DragEvent, useState } from "react";
import { useJobEvents } from "#/hooks/useJobEvents";
import { uploadVideo } from "#/lib/api";

export const Route = createFileRoute("/")({ component: UploadPage });

function UploadPage() {
	const [file, setFile] = useState<File | null>(null);
	const [dragOver, setDragOver] = useState(false);
	const [uploadPercent, setUploadPercent] = useState(0);
	const [jobId, setJobId] = useState<string | null>(null);

	const upload = useMutation({
		mutationFn: (f: File) => uploadVideo(f, setUploadPercent),
		onMutate: () => {
			setUploadPercent(0);
			setJobId(null);
		},
		onSuccess: (res) => setJobId(res.job_id),
	});
	const job = useJobEvents(jobId);

	const onDrop = (e: DragEvent) => {
		e.preventDefault();
		setDragOver(false);
		const dropped = e.dataTransfer.files[0];
		if (dropped) setFile(dropped);
	};

	return (
		<main className="min-h-screen bg-zinc-50 px-4 py-10 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
			<div className="mx-auto max-w-xl rounded-xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
				<h1 className="text-xl font-semibold">Video converter</h1>
				<p className="mt-1 mb-5 text-zinc-500">
					Upload a video, then watch conversion progress live.
				</p>

				<form
					onSubmit={(e) => {
						e.preventDefault();
						if (file) upload.mutate(file);
					}}
				>
					<label
						onDragOver={(e) => {
							e.preventDefault();
							setDragOver(true);
						}}
						onDragLeave={() => setDragOver(false)}
						onDrop={onDrop}
						className={`block cursor-pointer rounded-lg border-2 border-dashed px-4 py-7 text-center text-zinc-500 transition-colors hover:border-blue-500 ${
							dragOver
								? "border-blue-500"
								: "border-zinc-300 dark:border-zinc-700"
						}`}
					>
						<input
							type="file"
							accept="video/*"
							className="hidden"
							onChange={(e) => setFile(e.target.files?.[0] ?? null)}
						/>
						{file ? (
							<>
								<strong className="text-zinc-900 dark:text-zinc-100">
									{file.name}
								</strong>{" "}
								({(file.size / 1024 / 1024).toFixed(1)} MB)
							</>
						) : (
							<>
								<strong className="text-zinc-900 dark:text-zinc-100">
									Choose a video
								</strong>{" "}
								or drop it here
							</>
						)}
					</label>

					<button
						type="submit"
						disabled={!file || upload.isPending}
						className="mt-4 w-full rounded-lg bg-blue-600 py-2.5 font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
					>
						{upload.isPending ? "Uploading…" : "Upload"}
					</button>
				</form>

				{!upload.isIdle && (
					<section className="mt-5">
						<ProgressBar
							label="Upload"
							percent={upload.isPending ? uploadPercent : 100}
							state={
								upload.isError ? "error" : upload.isSuccess ? "done" : "running"
							}
						/>
						{upload.isError && (
							<p className="mt-2 font-semibold text-red-600 dark:text-red-400">
								{upload.error.message}
							</p>
						)}
					</section>
				)}

				{jobId && (
					<section className="mt-5">
						<ProgressBar
							label="Conversion"
							percent={job.percent}
							state={job.status}
							waiting={job.status === "connecting"}
						/>
						<p className="mt-4 break-all text-sm text-zinc-500">
							Job:{" "}
							<code className="text-zinc-900 dark:text-zinc-100">{jobId}</code>
						</p>

						{job.status === "done" && (
							<p className="mt-2 font-semibold text-green-600 dark:text-green-400">
								Done.{" "}
								{job.url && (
									<a href={job.url} className="text-blue-600 underline">
										Download
									</a>
								)}
							</p>
						)}
						{job.status === "error" && (
							<p className="mt-2 font-semibold text-red-600 dark:text-red-400">
								Failed: {job.error}
							</p>
						)}

						<pre className="mt-4 max-h-56 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-zinc-100 p-3 font-mono text-xs dark:bg-zinc-950">
							{job.log.join("\n")}
						</pre>
					</section>
				)}
			</div>
		</main>
	);
}

function ProgressBar({
	label,
	percent,
	state,
	waiting = false,
}: {
	label: string;
	percent: number;
	state: string;
	waiting?: boolean;
}) {
	const color =
		state === "error"
			? "bg-red-500"
			: state === "done"
				? "bg-green-500"
				: "bg-blue-500";

	return (
		<div>
			<div className="mb-1.5 flex justify-between text-sm text-zinc-500">
				<span>{label}</span>
				<span>{waiting ? "waiting…" : `${Math.round(percent)}%`}</span>
			</div>
			<div className="h-2 overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800">
				<div
					className={`h-full transition-all duration-200 ${color}`}
					style={{ width: `${percent}%` }}
				/>
			</div>
		</div>
	);
}

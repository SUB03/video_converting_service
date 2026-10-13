from celery import Celery
from celery.utils.log import get_task_logger

from video_converter_service.config import settings

celery_app = Celery("video_converter", broker=str(settings.rabbitmq_url))
celery_app.conf.update(
    task_default_queue=settings.convert_queue,
    task_ignore_result=True,
    # Ack only after the task finished, one task at a time: a crash means redelivery
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # send_task returns only once RabbitMQ has confirmed the message
    broker_transport_options={"confirm_publish": True},
    broker_connection_retry_on_startup=True,
    # Remote control (celery inspect/control) uses transient non-exclusive reply queues,
    # which RabbitMQ 4 refuses ("transient_nonexcl_queues is deprecated")
    worker_enable_remote_control=False,
)

logger = get_task_logger(__name__)


@celery_app.task(name="convert_video")
def convert_video(job_id: str, path: str, source_format: str, target_formats: list[str]):
    # TODO: skip if already done (job_id is the task id, so redeliveries repeat it),
    #       set status=processing, run ffmpeg per target format, set status=done
    logger.info(
        "placeholder: convert %s (%s) %s -> %s",
        job_id, path, source_format, ", ".join(target_formats),
    )

import copy
import rx
from collections import namedtuple
import dxpy.slurm as slurm
from .. import misc
from ..representation.templates import TaskScript, TaskCommand
from .service import update, update_complete
import dask


class Workers:
    @classmethod
    def is_complete(cls, task):
        return task.state == misc.TaskState.Complete

    @classmethod
    def on_this_worker(cls, task):
        return task.workers.type == cls.WorkerType

    @classmethod
    def plan(cls, task):
        raise NotImplementedError

    @classmethod
    def run(cls, task):
        cls.plan(task).subscribe()


class Slurm(Workers):
    WorkerType = misc.WorkerType.Slurm

    @classmethod
    def is_complete(cls, task):
        return slurm.is_complete(task.workers.info)

    @classmethod
    def plan(cls, task):
        def add_sid(sid):
            t = copy.deepcopy(task)
            t.workers.info = {'sid': sid}

        assert isinstance(
            task, TaskScript), 'Only TaskScript is supported: {!r}'.format(task)

        return (task.plan(interp='sbatch')
                .map(slurm.sid_from_submit)
                .map(add_sid)
                .map(update))


NB_THREADS = 5
THREAD_POOL = rx.concurrency.ThreadPoolScheduler(NB_THREADS)


class MultiThreding(Workers):
    WorkerType = misc.WorkerType.MultiThreading

    @classmethod
    def plan(cls, task):
        # TRT = namedtuple('TaskResultTuple', ('task', 'res'))
        (rx.Observable.just(task)
         .subscribe_on(THREAD_POOL)
         .map(lambda t: t.run())
         .map(lambda r: r.subscribe())
         .map(lambda r: update_complete(task)))


# class Dask(Workers):
#     WorkerType = misc.WorkerType.Dask
#     NB_PROCESSES = 5

#     @classmethod
#     def run_plan(cls, task):
#         (rx.Observable.just(task.workers.num_workers)
#          .map(lambda i: dask.delayed(task.run)(i_worker=i))
#          .to_list()
#          .map(lambda l: dask.bag.from_delayed(l))
#          .map(lambda b: b.compute(num_workers=NB_PROCESSES)))
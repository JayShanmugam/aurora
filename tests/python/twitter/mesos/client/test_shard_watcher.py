from math import ceil
import unittest

from twitter.mesos.client.health_check_factory import HealthCheck
from twitter.mesos.client.shard_watcher import ShardWatcher

from gen.twitter.mesos.constants import DEFAULT_ENVIRONMENT
from gen.twitter.mesos.ttypes import *
from gen.twitter.mesos.MesosSchedulerManager import Client as scheduler_client

import mox
import pytest


class FakeClock(object):
  def __init__(self):
    self._now_seconds = 0.0

  def time(self):
    return self._now_seconds

  def sleep(self, seconds):
    self._now_seconds += seconds


class FakeHealthCheckFactory(object):
  """Performs the functions of a health checker for testing"""
  def __init__(self):
    self._health_check = mox.MockObject(HealthCheck)

  def get(self):
    return self._health_check

  def expect_health_check(self, task, status, retry):
    self._health_check.health(task).InAnyOrder().AndReturn((status, retry))

  def replay(self):
    mox.Replay(self._health_check)

  def verify(self):
    mox.Verify(self._health_check)


def find_expected_cycles(period, sleep_secs):
  return ceil(period / sleep_secs) + 1


class ShardWatcherTest(unittest.TestCase):
  WATCH_SHARDS = range(3)
  RESTART_THRESHOLD = WATCH_SECS = 50
  EXPECTED_CYCLES = find_expected_cycles(WATCH_SECS, 3.0)

  def setUp(self):
    self._role = 'mesos'
    self._name = 'jimbob'
    self._clock = FakeClock()
    self._scheduler = mox.MockObject(scheduler_client)
    job = JobKey(name=self._name, environment=DEFAULT_ENVIRONMENT, role=self._role)
    self._health_check_handler = FakeHealthCheckFactory()
    self._watcher = ShardWatcher(self._scheduler,
                                 job,
                                 'cluster',
                                 self.RESTART_THRESHOLD,
                                 self.WATCH_SECS,
                                 has_health_port=True,
                                 health_check_interval_seconds=3,
                                 health_check_factory=self._health_check_handler,
                                 clock=self._clock)

  def get_tasks_status_query(self, shard_ids):
    query = TaskQuery()
    query.owner = Identity(role=self._role)
    query.jobName = self._name
    query.statuses = set([ScheduleStatus.RUNNING])
    query.shardIds = set(shard_ids)
    return query

  def create_task(self, shard_id):
    return ScheduledTask(assignedTask=AssignedTask(task=TwitterTaskInfo(shardId=shard_id)))

  def expect_get_statuses(self, shard_ids=WATCH_SHARDS, num_calls=EXPECTED_CYCLES):
    response = ScheduleStatusResponse(responseCode=ResponseCode.OK, message='test', tasks=[])
    response.tasks += [self.create_task(shard_id) for shard_id in shard_ids]
    query = self.get_tasks_status_query(shard_ids)
    for x in range(int(num_calls)):
      self._scheduler.getTasksStatus(query).AndReturn(response)

  def expect_health_check(self, shard, status, retry=True, num_calls=EXPECTED_CYCLES):
    for x in range(int(num_calls)):
      self._health_check_handler.expect_health_check(self.create_task(shard), status, retry)

  def assert_watch_result(self, expected_failed_shards, shards_to_watch=WATCH_SHARDS):
    shards_returned = self._watcher.watch(shards_to_watch)
    assert set(expected_failed_shards) == shards_returned, (
        'Expected shards (%s) : Returned shards (%s)' % (expected_failed_shards, shards_returned))

  def replay_mocks(self):
    mox.Replay(self._scheduler)
    self._health_check_handler.replay()

  def verify_mocks(self):
    mox.Verify(self._scheduler)
    self._health_check_handler.verify()

  def test_successful_watch(self):
    """All shards are healthy immediately"""
    self.expect_get_statuses()
    self.expect_health_check(0, True)
    self.expect_health_check(1, True)
    self.expect_health_check(2, True)
    self.replay_mocks()
    self.assert_watch_result([])
    self.verify_mocks()

  def test_single_shard_failure(self):
    """One failed shard in a batch of shards"""
    self.expect_get_statuses()
    self.expect_health_check(0, False)
    self.expect_health_check(1, True)
    self.expect_health_check(2, True)
    self.replay_mocks()
    self.assert_watch_result([0])
    self.verify_mocks()

  def test_all_shard_failure(self):
    """All failed shard in a batch of shards"""
    self.expect_get_statuses()
    self.expect_health_check(0, False)
    self.expect_health_check(1, False)
    self.expect_health_check(2, False)
    self.replay_mocks()
    self.assert_watch_result([0, 1, 2])
    self.verify_mocks()

  def test_restart_threshold_fail_fast(self):
    """Shards are reported unhealthy with retry set to False"""
    self.expect_get_statuses(num_calls=1)
    self.expect_health_check(0, False, retry=False, num_calls=1)
    self.expect_health_check(1, False, retry=False, num_calls=1)
    self.expect_health_check(2, False, retry=False, num_calls=1)
    self.replay_mocks()
    self.assert_watch_result([0, 1, 2])
    self.verify_mocks()

  def test_restart_threshold(self):
    """Shards are reported healthy at the end of the restart_threshold"""
    self.expect_get_statuses(num_calls=self.EXPECTED_CYCLES - 1)
    self.expect_health_check(0, False, num_calls=self.EXPECTED_CYCLES - 1)
    self.expect_health_check(1, False, num_calls=self.EXPECTED_CYCLES - 1)
    self.expect_health_check(2, False, num_calls=self.EXPECTED_CYCLES - 1)
    self.expect_get_statuses()
    self.expect_health_check(0, True)
    self.expect_health_check(1, True)
    self.expect_health_check(2, True)
    self.replay_mocks()
    self.assert_watch_result([])
    self.verify_mocks()

  def test_watch_period_failure(self):
    """Shards are reported unhealthy before watch_secs expires"""
    self.expect_get_statuses()
    self.expect_health_check(0, True, num_calls=self.EXPECTED_CYCLES - 1)
    self.expect_health_check(1, True, num_calls=self.EXPECTED_CYCLES - 1)
    self.expect_health_check(2, True, num_calls=self.EXPECTED_CYCLES - 1)
    self.expect_health_check(0, False, num_calls=1)
    self.expect_health_check(1, False, num_calls=1)
    self.expect_health_check(2, False, num_calls=1)
    self.replay_mocks()
    self.assert_watch_result([0, 1, 2])
    self.verify_mocks()

  def test_single_watch_period_failure(self):
    """One shard is reported unhealthy before watch_secs expires"""
    self.expect_get_statuses()
    self.expect_health_check(0, True)
    self.expect_health_check(1, True)
    self.expect_health_check(2, True, num_calls=self.EXPECTED_CYCLES - 1)
    self.expect_health_check(2, False, num_calls=1)
    self.replay_mocks()
    self.assert_watch_result([2])
    self.verify_mocks()
from django.utils import timezone
from django.test import TestCase
from dateutil.relativedelta import relativedelta

from squad.core.models import Group, ProjectStatus, MetricThreshold


def h(n):
    """
    h(n) = n hours ago
    """
    return timezone.now() - relativedelta(hours=n)


class ProjectStatusTest(TestCase):

    def setUp(self):
        self.group = Group.objects.create(slug='mygroup')
        self.project = self.group.projects.create(slug='myproject')
        self.environment = self.project.environments.create(slug='theenvironment')
        self.suite = self.project.suites.create(slug='/')

    def create_build(self, v, datetime=None, create_test_run=True):
        build = self.project.builds.create(version=v, datetime=datetime)
        if create_test_run:
            build.test_runs.create(environment=self.environment)
        return build

    def test_status_of_first_build(self):
        build = self.create_build('1')
        status = ProjectStatus.create_or_update(build)

        self.assertEqual(build, status.build)
        self.assertIsNone(status.get_previous())

    def test_status_of_second_build(self):
        build = self.create_build('1')
        status1 = ProjectStatus.create_or_update(build)

        build2 = self.create_build('2')
        status2 = ProjectStatus.create_or_update(build2)
        self.assertEqual(status1, status2.get_previous())
        self.assertEqual(build2, status2.build)

    def test_dont_record_the_same_status_twice(self):
        build = self.create_build('1')
        status1 = ProjectStatus.create_or_update(build)
        status2 = ProjectStatus.create_or_update(build)
        self.assertEqual(status1, status2)
        self.assertEqual(1, ProjectStatus.objects.count())

    def test_wait_for_build_completion(self):
        build = self.create_build('1', datetime=h(1), create_test_run=False)
        status = ProjectStatus.create_or_update(build)
        self.assertFalse(status.finished)

    def test_first_build(self):
        build = self.create_build('1')
        status = ProjectStatus.create_or_update(build)
        self.assertEqual(build, status.build)

    def test_build_not_finished(self):
        build = self.create_build('2', datetime=h(4), create_test_run=False)
        status = ProjectStatus.create_or_update(build)
        self.assertFalse(status.finished)

    def test_test_summary(self):
        build = self.create_build('1', datetime=h(10))
        test_run = build.test_runs.first()
        test_run.tests.create(name='foo', suite=self.suite, result=True)
        test_run.tests.create(name='bar', suite=self.suite, result=False)
        test_run.tests.create(name='baz', suite=self.suite, result=None)

        status = ProjectStatus.create_or_update(build)
        self.assertEqual(1, status.tests_pass)
        self.assertEqual(1, status.tests_fail)
        self.assertEqual(1, status.tests_skip)
        self.assertEqual(3, status.tests_total)

    def test_metrics_summary(self):
        build = self.create_build('1', datetime=h(10))
        test_run = build.test_runs.first()
        test_run.metrics.create(name='foo', suite=self.suite, result=2)
        test_run.metrics.create(name='bar', suite=self.suite, result=2)

        status = ProjectStatus.create_or_update(build)
        self.assertEqual(2.0, status.metrics_summary)

    def test_updates_data_as_new_testruns_arrive(self):
        build = self.create_build('1', datetime=h(10))
        test_run1 = build.test_runs.first()
        test_run1.tests.create(name='foo', suite=self.suite, result=True)
        ProjectStatus.create_or_update(build)

        test_run2 = build.test_runs.create(environment=self.environment)
        test_run2.tests.create(name='bar', suite=self.suite, result=True)
        test_run2.tests.create(name='baz', suite=self.suite, result=False)
        test_run2.tests.create(name='qux', suite=self.suite, result=None)
        test_run2.metrics.create(name='v1', suite=self.suite, result=5.0)
        status = ProjectStatus.create_or_update(build)

        self.assertEqual(2, status.tests_pass)
        self.assertEqual(1, status.tests_fail)
        self.assertEqual(1, status.tests_skip)
        self.assertEqual(status.tests_pass, build.status.tests_pass)
        self.assertEqual(status.tests_fail, build.status.tests_fail)
        self.assertEqual(status.tests_skip, build.status.tests_skip)
        self.assertAlmostEqual(5.0, status.metrics_summary)
        self.assertEqual(status.metrics_summary, build.status.metrics_summary)

    def test_populates_last_updated(self):
        build = self.create_build('1', datetime=h(10))
        status = ProjectStatus.create_or_update(build)
        self.assertIsNotNone(status.last_updated)

    def test_updates_last_updated(self):
        build = self.create_build('1', datetime=h(10))
        test_run1 = build.test_runs.first()
        test_run1.tests.create(name='foo', suite=self.suite, result=True)
        status = ProjectStatus.create_or_update(build)
        old_date = status.last_updated

        build.test_runs.create(environment=self.environment)
        status = ProjectStatus.create_or_update(build)

        self.assertNotEqual(status.last_updated, old_date)

    def test_previous_must_be_finished(self):
        self.environment.expected_test_runs = 2
        self.environment.save()

        # finished
        build1 = self.create_build('1', datetime=h(10), create_test_run=False)
        build1.test_runs.create(environment=self.environment)
        build1.test_runs.create(environment=self.environment)
        status1 = ProjectStatus.create_or_update(build1)

        # not finished
        build2 = self.create_build('2', datetime=h(5), create_test_run=False)
        ProjectStatus.create_or_update(build2)

        # current build
        build = self.create_build('3', datetime=h(0), create_test_run=False)
        status = ProjectStatus.create_or_update(build)

        self.assertEqual(status1, status.get_previous())

    def test_previous_must_be_from_the_same_project(self):
        previous_build = self.create_build('1', datetime=h(10))
        previous = ProjectStatus.create_or_update(previous_build)

        other_project = self.group.projects.create(slug='other_project')
        other_env = other_project.environments.create(slug='other_env')
        other_build = other_project.builds.create(version='1', datetime=h(5))
        other_build.test_runs.create(environment=other_env)
        ProjectStatus.create_or_update(other_build)

        build = self.create_build('2', datetime=h(0))
        status = ProjectStatus.create_or_update(build)
        self.assertEqual(previous, status.get_previous())

    def test_zero_expected_test_runs(self):
        self.project.environments.create(slug='other_env', expected_test_runs=0)

        build = self.create_build('1')

        status = ProjectStatus.create_or_update(build)
        self.assertTrue(status.finished)

    def test_cache_test_run_counts(self):
        build = self.create_build('1', create_test_run=False)
        build.test_runs.create(environment=self.environment, completed=True)
        build.test_runs.create(environment=self.environment, completed=True)
        build.test_runs.create(environment=self.environment, completed=False)

        status = ProjectStatus.create_or_update(build)

        self.assertEqual(3, status.test_runs_total)
        self.assertEqual(2, status.test_runs_completed)
        self.assertEqual(1, status.test_runs_incomplete)

    def test_cache_test_run_counts_on_update(self):
        build = self.create_build('1', create_test_run=False)
        ProjectStatus.create_or_update(build)

        build.test_runs.create(environment=self.environment, completed=True)
        build.test_runs.create(environment=self.environment, completed=False)
        status = ProjectStatus.create_or_update(build)
        self.assertEqual(2, status.test_runs_total)
        self.assertEqual(1, status.test_runs_completed)
        self.assertEqual(1, status.test_runs_incomplete)

    def test_cache_regressions(self):
        build1 = self.create_build('1', datetime=h(10))
        test_run1 = build1.test_runs.first()
        test_run1.tests.create(name='foo', suite=self.suite, result=True)
        ProjectStatus.create_or_update(build1)

        build2 = self.create_build('2', datetime=h(9))
        test_run2 = build2.test_runs.first()
        test_run2.tests.create(name='foo', suite=self.suite, result=False)
        status = ProjectStatus.create_or_update(build2)

        self.assertIsNotNone(status.regressions)
        self.assertIsNone(status.fixes)

    def test_cache_regressions_update(self):
        build1 = self.create_build('1', datetime=h(10))
        test_run1 = build1.test_runs.first()
        test_run1.tests.create(name='foo', suite=self.suite, result=True)
        ProjectStatus.create_or_update(build1)

        build2 = self.create_build('2', datetime=h(9))
        test_run2 = build2.test_runs.first()
        test_run2.tests.create(name='foo', suite=self.suite, result=True)
        status1 = ProjectStatus.create_or_update(build2)

        self.assertIsNone(status1.regressions)
        self.assertIsNone(status1.fixes)

        build3 = self.create_build('3', datetime=h(8))
        test_run3 = build3.test_runs.first()
        test_run3.tests.create(name='foo', suite=self.suite, result=False)
        status2 = ProjectStatus.create_or_update(build3)

        self.assertIsNotNone(status2.regressions)
        self.assertIsNone(status2.fixes)

    def test_cache_fixes(self):
        build1 = self.create_build('1', datetime=h(10))
        test_run1 = build1.test_runs.first()
        test_run1.tests.create(name='foo', suite=self.suite, result=False)
        ProjectStatus.create_or_update(build1)

        build2 = self.create_build('2', datetime=h(9))
        test_run2 = build2.test_runs.first()
        test_run2.tests.create(name='foo', suite=self.suite, result=True)
        status = ProjectStatus.create_or_update(build2)

        self.assertIsNotNone(status.fixes)
        self.assertIsNone(status.regressions)

    def test_cache_fixes_update(self):
        build1 = self.create_build('1', datetime=h(10))
        test_run1 = build1.test_runs.first()
        test_run1.tests.create(name='foo', suite=self.suite, result=False)
        ProjectStatus.create_or_update(build1)

        build2 = self.create_build('2', datetime=h(9))
        test_run2 = build2.test_runs.first()
        test_run2.tests.create(name='foo', suite=self.suite, result=False)
        status1 = ProjectStatus.create_or_update(build2)

        self.assertIsNone(status1.fixes)
        self.assertIsNone(status1.regressions)

        build3 = self.create_build('3', datetime=h(8))
        test_run3 = build3.test_runs.first()
        test_run3.tests.create(name='foo', suite=self.suite, result=True)
        status2 = ProjectStatus.create_or_update(build3)

        self.assertIsNotNone(status2.fixes)
        self.assertIsNone(status2.regressions)

    def test_get_exceeded_thresholds(self):
        build = self.create_build('1')
        testrun = build.test_runs.create(
            environment=self.environment)
        testrun.metrics.create(name='metric1', suite=self.suite, result=3)
        testrun.metrics.create(name='metric2', suite=self.suite, result=2)
        testrun.metrics.create(name='metric1', suite=self.suite, result=5)
        status = ProjectStatus.create_or_update(build)
        MetricThreshold.objects.create(project=self.project,
                                       name='metric1', value=4,
                                       is_higher_better=True)

        thresholds = status.get_exceeded_thresholds()
        self.assertEqual(len(thresholds), 1)
        self.assertEqual(thresholds[0][1].name, 'metric1')
        self.assertEqual(thresholds[0][1].result, 3)

    def test_last_build_comparison(self):
        # Test that the build that we compare against is truly the last one
        # time wise.
        build1 = self.create_build('1', datetime=h(10))
        test_run1 = build1.test_runs.first()
        test_run1.tests.create(name='foo', suite=self.suite, result=False)
        test_run1.tests.create(name='bar', suite=self.suite, result=False)
        ProjectStatus.create_or_update(build1)

        build2 = self.create_build('2', datetime=h(9))
        test_run2 = build2.test_runs.first()
        test_run2.tests.create(name='foo', suite=self.suite, result=False)
        test_run2.tests.create(name='bar', suite=self.suite, result=True)
        ProjectStatus.create_or_update(build2)

        build3 = self.create_build('3', datetime=h(8))
        test_run3 = build3.test_runs.first()
        test_run3.tests.create(name='foo', suite=self.suite, result=True)
        test_run3.tests.create(name='bar', suite=self.suite, result=True)
        status3 = ProjectStatus.create_or_update(build3)

        fixes3 = status3.get_fixes()
        self.assertEqual(len(fixes3['theenvironment']), 1)
        self.assertEqual(fixes3['theenvironment'][0], 'foo')

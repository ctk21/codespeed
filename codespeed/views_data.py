# -*- coding: utf-8 -*-
from __future__ import absolute_import

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import get_object_or_404

from codespeed.models import (
    Executable, Revision, Project, Branch,
    Environment, Benchmark, Result)


def get_default_environment(enviros, data, multi=False):
    """Returns the default environment. Preference level is:
        * Present in URL parameters (permalinks)
        * Value in settings.py
        * First Environment ID

    """
    defaultenviros = []
    # Use permalink values
    if 'env' in data:
        for env_value in data['env'].split(","):
            for env in enviros:
                try:
                    env_id = int(env_value)
                except ValueError:
                    # Not an int
                    continue
                for env in enviros:
                    if env_id == env.id:
                        defaultenviros.append(env)
            if not multi:
                break
    # Use settings.py value
    if not defaultenviros:
        if (hasattr(settings, 'DEF_ENVIRONMENT') and
                settings.DEF_ENVIRONMENT is not None):
            for env in enviros:
                if settings.DEF_ENVIRONMENT == env.name:
                    defaultenviros.append(env)
                    break
    # Last fallback
    if not defaultenviros:
        defaultenviros = enviros
    if multi:
        return defaultenviros
    else:
        return defaultenviros[0]


def getbaselineexecutables():
    baseline = [{
        'key': "none",
        'name': "None",
        'executable': "none",
        'revision': "none",
    }]
    executables = Executable.objects.select_related('project')
    revs = Revision.objects.exclude(tag="").select_related('branch__project')
    maxlen = 22
    for rev in revs:
        # Add executables that correspond to each tagged revision.
        for exe in [e for e in executables if e.project == rev.branch.project]:
            exestring = str(exe)
            if len(exestring) > maxlen:
                exestring = str(exe)[0:maxlen] + "..."
            name = exestring + " " + rev.tag
            key = str(exe.id) + "+" + str(rev.id)
            baseline.append({
                'key': key,
                'executable': exe,
                'revision': rev,
                'name': name,
            })
    # move default to first place
    defaultbaseline = None
    if hasattr(settings, 'DEF_BASELINE') and settings.DEF_BASELINE is not None:
        try:
            def match_on_tag(x):
                return x['executable'].name == settings.DEF_BASELINE['executable'] and x['revision'].tag.strip() == settings.DEF_BASELINE['tag']

            def match_on_rev(x):
                return x['executable'].name == settings.DEF_BASELINE['executable'] and x['revision'].commitid == settings.DEF_BASELINE['revision']

            is_match = match_on_tag if 'tag' in settings.DEF_BASELINE else match_on_rev

            for base in baseline:
                if base['key'] == "none":
                    continue
                if is_match(base):
                    defaultbaseline = str(base['executable'].id) + "+" + str(base['revision'].id)
                    break
        except KeyError:
            # TODO: write to server logs
            # error in settings.DEF_BASELINE
            pass
    return baseline, defaultbaseline


def getdefaultexecutable():
    default = None
    if (hasattr(settings, 'DEF_EXECUTABLE') and
            settings.DEF_EXECUTABLE is not None):
        try:
            default = Executable.objects.get(name=settings.DEF_EXECUTABLE)
        except Executable.DoesNotExist:
            pass
    if default is None:
        execquery = Executable.objects.filter(project__track=True)
        if len(execquery):
            default = execquery[0]

    return default


def getcomparisonexes():
    all_executables = {}
    exekeys = []
    baselines, _ = getbaselineexecutables()
    for proj in Project.objects.all():
        executables = []
        executablekeys = []
        maxlen = 20
        # add all tagged revs for any project
        for exe in baselines:
            if exe['key'] != "none" and exe['executable'].project == proj:
                executablekeys.append(exe['key'])
                executables.append(exe)

        # add latest revs of the project
        branches = Branch.objects.filter(project=proj)
        for branch in branches:
            try:
                rev = Revision.objects.filter(branch=branch).latest('date')
            except Revision.DoesNotExist:
                continue
            # Now only append when tag == "",
            # because we already added tagged revisions
            if rev.tag == "":
                for exe in Executable.objects.filter(project=proj):
                    exestring = str(exe)
                    if len(exestring) > maxlen:
                        exestring = str(exe)[0:maxlen] + "..."
                    name = exestring + " latest"
                    if branch.name != 'default':
                        name += " in branch '" + branch.name + "'"
                    key = str(exe.id) + "+L+" + branch.name
                    executablekeys.append(key)
                    executables.append({
                        'key': key,
                        'executable': exe,
                        'revision': rev,
                        'name': name,
                    })
        all_executables[proj] = executables
        exekeys += executablekeys
    return all_executables, exekeys


def get_benchmark_results(data):
    environment = Environment.objects.get(name=data['env'])
    project = Project.objects.get(name=data['proj'])
    executable = Executable.objects.get(name=data['exe'], project=project)
    branch = Branch.objects.get(name=data['branch'], project=project)
    benchmark = Benchmark.objects.get(name=data['ben'])

    number_of_revs = int(data.get('revs', 10))

    baseline_commit_name = (data['base_commit'] if 'base_commit' in data
                            else None)
    relative_results = (
        ('relative' in data and data['relative'] in ['1', 'yes']) or
        baseline_commit_name is not None)

    result_query = Result.objects.filter(
        benchmark=benchmark
    ).filter(
        environment=environment
    ).filter(
        executable=executable
    ).filter(
        revision__project=project
    ).filter(
        revision__branch=branch
    ).select_related(
        "revision"
    ).order_by('-date')[:number_of_revs]

    if len(result_query) == 0:
        raise ObjectDoesNotExist("No results were found!")

    result_list = [item for item in result_query]
    result_list.reverse()

    if relative_results:
        ref_value = result_list[0].value

    if baseline_commit_name is not None:
        baseline_env = environment
        baseline_proj = project
        baseline_exe = executable
        baseline_branch = branch

        if 'base_env' in data:
            baseline_env = Environment.objects.get(name=data['base_env'])
        if 'base_proj' in data:
            baseline_proj = Project.objects.get(name=data['base_proj'])
        if 'base_exe' in data:
            baseline_exe = Executable.objects.get(name=data['base_exe'],
                                                  project=baseline_proj)
        if 'base_branch' in data:
            baseline_branch = Branch.objects.get(name=data['base_branch'],
                                                 project=baseline_proj)

        base_data = Result.objects.get(
                                benchmark=benchmark,
                                environment=baseline_env,
                                executable=baseline_exe,
                                revision__project=baseline_proj,
                                revision__branch=baseline_branch,
                                revision__commitid=baseline_commit_name)

        ref_value = base_data.value

    if relative_results:
        for element in result_list:
            element.value = (100 * (element.value - ref_value)) / ref_value

    return {
            'environment': environment,
            'project': project,
            'executable': executable,
            'branch': branch,
            'benchmark': benchmark,
            'results': result_list,
            'relative': relative_results,
           }


def get_num_revs_and_benchmarks(data):
    if data['ben'] == 'grid':
        benchmarks = Benchmark.objects.all().order_by('name')
        number_of_revs = 15
    elif data['ben'] == 'show_none':
        benchmarks = []
        number_of_revs = int(data.get('revs', 10))
    else:
        benchmarks = [get_object_or_404(Benchmark, name=data['ben'])]
        number_of_revs = int(data.get('revs', 10))
    return number_of_revs, benchmarks


def get_stats_with_defaults(res):
    val_min = ""
    if res.val_min is not None:
        val_min = res.val_min
    val_max = ""
    if res.val_max is not None:
        val_max = res.val_max
    q1 = ""
    if res.q1 is not None:
        q1 = res.q1
    q3 = ""
    if res.q3 is not None:
        q3 = res.q3
    return q1, q3, val_max, val_min

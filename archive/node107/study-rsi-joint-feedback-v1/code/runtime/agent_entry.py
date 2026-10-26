"""Run a frozen workflow after installing only new-server wiring."""
import argparse
import runpy
import sys
from libero_runtime import install_agent_runtime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workflow', default='feedback_workflow.py')
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.workflow not in ('feedback_workflow.py', 'stress_workflow.py'):
        parser.error('unsupported workflow')
    paths = install_agent_runtime()
    arguments = args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments
    workflow = paths.source / args.workflow
    sys.argv = [str(workflow)] + arguments
    runpy.run_path(str(workflow), run_name='__main__')


if __name__ == '__main__':
    main()

#!/usr/bin/env python

from __future__ import print_function

import logging
import time
import threading
import sys
is_py2 = sys.version[0] == '2'
if is_py2:
    from Queue import Queue as queue
else:
    from queue import queue as queue

import thriftpy
poc_thrift = thriftpy.load('../poc.thrift', module_name='poc_thrift')
from thriftpy.rpc import client_context
import thriftpy.transport

logging.basicConfig(level=logging.INFO)

__author__ = 'Curtis West'
__copyright__ = 'Copyright 2017, Curtis West'
__version__ = '2.0a'
__maintainer__ = 'Curtis West'
__email__ = 'curtis@curtiswest.net'
__status__ = 'Development'


class Worker(threading.Thread):
    """
    Workers take a queue of `tasks` and pop it off the queue and do the requested work on it. The `callback` function
    associated with that task is then called on the result.
    """

    def __init__(self, tasks):
        super(Worker, self).__init__()
        self.tasks = tasks
        self.daemon = True
        self.start()

    def run(self):
        while True:
            callback, func, args, kargs = self.tasks.get()
            try:
                callback(func(*args, **kargs))
            except Exception as e:
                print(e)
            finally:
                self.tasks.task_done()


class ThreadPool(object):
    """
    ThreadPool holds a number of threads that take units of work and complete them in a multi-threaded fashion. This is
    useful when waiting on a range of responses, where consecutive execution would cause delays, but true
    multiprocessing is not necessary.
    """

    def __init__(self, num_threads):
        self.tasks = queue(num_threads)
        for _ in range(num_threads):
            Worker(self.tasks)

    def add_task(self, callback, func, *args, **kargs):
        self.tasks.put((callback, func, args, kargs))

    def map(self, callback, func, args_list):
        for args in args_list:
            self.add_task(callback, func, args)

    def wait_completion(self):
        self.tasks.join()


class Heartbeater(threading.Thread):
    def __init__(self, min_interval, base_ip):
        # type: (int, str) -> None
        base_ip = base_ip.rstrip()
        if base_ip[-1:] != '.':
            raise ValueError('Last character in base_ip must be a dot, e.g. "192.168.1."')
        super(Heartbeater, self).__init__()
        self.daemon = True
        self.server_dict = dict()
        self.pool = ThreadPool(50)
        self.min_interval = min_interval
        self.base_ip = base_ip

    def _add_to_server_dict(self, args):
        # type: ((str, bool)) -> None
        self.server_dict[args[0]] = args[1]

    @staticmethod
    def ping_server_at_ip(ip):
        # type: (str) -> (str, bool)
        try:
            with client_context(poc_thrift.ImagingServer, ip, 6000, connect_timeout=100) as c:
                c.ping()
        except thriftpy.transport.TTransportException:
            return ip, False
        else:
            return ip, True

    def _sweep_ips_for_servers(self, base_ip):
        # type: (str) -> None
        self.pool.map(self._add_to_server_dict, self.ping_server_at_ip, [base_ip + str(x) for x in range(255)])
        self.pool.wait_completion()

    def inform_server_dead(self, server):
        # type: (str) -> None
        self.server_dict.pop(server, None)

    def run(self):
        self._sweep_ips_for_servers(base_ip=self.base_ip)
        start_time = time.time()
        while True:
            if (time.time() - start_time) > self.min_interval:
                start_time = time.time()
                self._sweep_ips_for_servers(base_ip=self.base_ip)
            else:
                time.sleep(0.1)
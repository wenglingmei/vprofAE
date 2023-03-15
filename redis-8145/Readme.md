# Testing redis-8145
In this test case, we need to generate a cluster on Redis server.
We provide two test scripts:
19-cluster-node-slots.bug.tcl is for buggy run and 19-cluster-node-slots.norm.tcl is for the baseline.
The main difference between them is on the number of the nodes.
In the evaluation, the node number is set to 400, which can fail the test sometimes for some
unknown reason. What we can do is to repeat the buggy run.
In this directory, we set a 40-nodes cluster for the buggy run and a 20-nodes cluster for the baseline,
to provide a smooth testing.

## The one click run
```
$ ./test.sh
```
## If the 40-node cluster still fails in your test, try to repeat the buggy case:
```
$ ./run_bug.sh
```

## Post-Profiling analysis can be run with the script:
```
$./analyze.sh
```
It produce result/vprof_profile.txt. In the file, the functions are ranked based on the cost. Each of the entry
will annotated with variable, locations that the anomalous value accessed, and the corrresponding  bug pettern.

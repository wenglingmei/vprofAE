# Optimize CLUSTER NODES command by generating all nodes slot topology firstly
source "../tests/includes/init-tests.tcl"
proc cluster_allocate_with_continuous_slots {n} {
    set slot 16383
    set avg [expr ($slot+1) / $n]
    while {$slot >= 0} {
        set node [expr $slot/$avg >= $n ? $n-1 : $slot/$avg]
        lappend slots_$node $slot
        incr slot -1
    }
    for {set j 0} {$j < $n} {incr j} {
        R $j cluster addslots {*}[set slots_${j}]
    }
}
proc cluster_create_with_continuous_slots {masters slaves} {
    cluster_allocate_with_continuous_slots $masters
    if {$slaves} {
        cluster_allocate_slaves $masters $slaves
    }
    assert_cluster_state ok
}
 proc uniqkey { } {
     set key   [ expr { pow(2,31) + [ clock clicks ] } ]
     set key   [ string range $key end-8 end-3 ]
     set key   [ clock seconds ]$key
     return $key
 }

 proc sleep { ms } {
     set uniq [ uniqkey ]
     set ::__sleep__tmp__$uniq 0
     after $ms set ::__sleep__tmp__$uniq 1
     vwait ::__sleep__tmp__$uniq
     unset ::__sleep__tmp__$uniq
 }

set n_node 10
set master_node 5
set slave_node 5

test "Create a $n_node nodes cluster" {
    cluster_create_with_continuous_slots $master_node $slave_node
}
test "Cluster should start ok" {
    assert_cluster_state ok
    #puts "Begin sleep for 50 seconds, connect perf please..."
    #sleep 50000
    #set ret [exec pgrep -d ',' -x redis-server]
    #set sudo [sudo:run [exec perf record -F 99 -p $ret -g &]]
    #vwait ${sudo}(done)
    #set ret [exec pidof redis-server]
    #puts $ret
}
set master1 [Rn 0]
set master2 [Rn 1]
set master3 [Rn 2]
set master4 [Rn 3]
set master5 [Rn 4]
set master6 [Rn 5]
set master7 [Rn 6]
set master8 [Rn 7]
set master9 [Rn 8]
set master10 [Rn 9]

test "slots distribution" {
    set repeat 20
    $master1 CLUSTER DELSLOTS 4095 4096 12286 12287 12288 
    set j 0; while {$j < $repeat} {
      set i 0 ; while {$i < 10}  {
	      set ret [R $i cluster nodes]
	      puts $ret
	      incr i
      }
      incr j
    }
    # Remove middle slots
    $master1 CLUSTER DELSLOTS 4092 4094 5000
    set j 0; while {$j < $repeat} {
      set i 0 ; while {$i < 10}  {
	      set ret [R $i cluster nodes]
	      puts $ret
	      incr i
      }
      incr j
    }
    # Remove head slots
    $master1 CLUSTER DELSLOTS 0 2 10 12 18 311 421 531
    set j 0; while {$j < $repeat} {
      set i 0 ; while {$i < 10}  {
	      set ret [R $i cluster nodes]
	      puts $ret
	      incr i
      }
      incr j
    }
    # Remove tail slots
    $master1 CLUSTER DELSLOTS 6380 6382 6383 6350 6352 6353 16350 16352 16353
    set j 0; while {$j < $repeat} {
      set i 0 ; while {$i < 10}  {
	      set ret [R $i cluster nodes]
	      puts $ret
	      incr i
      }
      incr j
    }
}

#test "Shutdown cluster nodes" {
#    set i 0 ; while {$i<120}  {
#      set ret [R $i shutdown nosave]
#      puts $ret
#      incr i
#    }
#}


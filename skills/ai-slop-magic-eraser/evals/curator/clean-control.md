# Cache warmup

The product search cache starts empty after a deploy, and the first searches
after a restart take about four seconds instead of 200 milliseconds. We warm it
before routing traffic to the new instances.

## Warming a new instance

1. Run `searchctl warm --instance <instance-id>`, where `<instance-id>` is the
   identifier the deploy job prints for each new instance.
2. Wait for the command to report `warm: 5000 queries replayed`, which takes
   about 90 seconds.
3. Add the instance to the load balancer with `lbctl add <instance-id>`.

The warmup replays the 5,000 most frequent searches from the previous day, so a
deploy right after midnight warms against a full day of traffic rather than a
partial one.

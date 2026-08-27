The `custom-awd-console` integrator script and its installer land in M2, once
tenant onboarding exists to issue the slug and secret they take as arguments.

See DESIGN.md §10 for the contract they must implement — in particular that the
script must never block or raise: the Wazuh integrator forks a process per alert,
so a hung script becomes a fork bomb on a client's manager.

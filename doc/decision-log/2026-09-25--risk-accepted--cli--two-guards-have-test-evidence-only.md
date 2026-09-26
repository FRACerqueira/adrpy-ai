# The check folderlog warning and the config overlap refusal have test evidence only

S11 and S12 were built so a real agent would trigger the Round 46 guards. The log refusal and the explore preview refusal fired in real runs; the check warning about a file in folderlog and the config --migrationpattern refusal never did, because agents went straight to log or previewed first as the skill says. Both are covered by automated tests; forcing them with an artificial scenario was declined by the owner (0be5f3b).

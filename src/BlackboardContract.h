// Method-only view of the game's squad Blackboard for the contract entry points (`contract-bodyguard`).
// Same approach as components/STOBE NativeAiAwareness.cpp: kenshi/AI/Blackboard.h is not included (it pulls in
// AI types this plugin does not need); these out-of-line members are resolved from KenshiLib.lib by their
// mangled names (?setContractJob@Blackboard@@QEAAXPEAVGameData@@AEBVhand@@@Z and friends). The class is never
// allocated or sized here: only pointers from Platoon::getBlackboard() are used. Include after the kenshi headers
// (GameData, hand, TimeOfDay).
#pragma once
#include <kenshi/GameData.h>
#include <kenshi/util/TimeOfDay.h>
#include <kenshi/util/hand.h>
#include <string>

class Blackboard {
public:
  // SDK Blackboard.h: public setContractJob(packageCollection, giver) RVA 0x272290 (the dialogue/hire entry point);
  // _setContractJob(package, hours, giver) RVA 0x271D90 (exported with public linkage); hours <= 0 = default length.
  void setContractJob(GameData *packageCollection, const hand &giver);
  void _setContractJob(GameData *package, int hours, const hand &giver);
  void endContractJob();
  bool hasContractJob() const;
  TimeOfDay getContractExpiryTime() const;
  std::string getCurrentAIPackageName() const;
};

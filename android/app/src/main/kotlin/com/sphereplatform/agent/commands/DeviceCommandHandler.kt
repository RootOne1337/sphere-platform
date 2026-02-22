package com.sphereplatform.agent.commands

import javax.inject.Inject
import javax.inject.Singleton

/**
 * DeviceCommandHandler — фасад для обратной совместимости с SphereAgentService.
 * Реальная диспетчеризация команд выполняется через [CommandDispatcher].
 * @see CommandDispatcher
 */
@Singleton
class DeviceCommandHandler @Inject constructor(
    val dispatcher: CommandDispatcher,
) {
    fun start() = dispatcher.start()
}


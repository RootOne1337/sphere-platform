package com.sphereplatform.agent.ota

import java.io.IOException

/** A submitted PackageInstaller session still requires explicit Android user approval. */
class OtaUserActionRequiredException(val sessionId: Int) : IOException("ota_install_requires_user_action")

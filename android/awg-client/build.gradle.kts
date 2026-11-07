plugins { alias(libs.plugins.android.application) }
android {
    namespace = "com.sphereplatform.awgclientprobe"
    compileSdk = 35
    defaultConfig { applicationId = "com.sphereplatform.awgclientprobe"; minSdk = 26; targetSdk = 35; versionCode = 1; versionName = "0.1-diagnostic" }
}
androidComponents.beforeVariants(androidComponents.selector().withBuildType("release")) { it.enable = false }

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.serialization)
}
val sharedSources = tasks.register<Copy>("stageSharedVpnSources") {
    from(rootProject.file("app/src/main/kotlin")) {
        include("com/sphereplatform/agent/vpn/AppScopedVpnPreparation.kt", "com/sphereplatform/agent/vpn/AppScopedVpnSession.kt",
            "com/sphereplatform/agent/vpn/SelectedUidGuard.kt", "com/sphereplatform/agent/commands/BoundedProcessRunner.kt")
    }
    into(layout.buildDirectory.dir("generated/sharedVpn"))
}
android {
    namespace = "com.sphereplatform.awgprobe"
    compileSdk = 35
    defaultConfig { applicationId = "com.sphereplatform.awgprobe"; minSdk = 26; targetSdk = 35; versionCode = 1; versionName = "0.1-diagnostic" }
    providers.gradleProperty("sphereProbeAbi").orNull?.let { abi ->
        require(abi in setOf("x86_64", "arm64-v8a", "armeabi-v7a"))
        defaultConfig.ndk.abiFilters.add(abi)
    }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
    sourceSets.getByName("main").java.srcDir(layout.buildDirectory.dir("generated/sharedVpn"))
}
tasks.named("preBuild").configure { dependsOn(sharedSources) }
androidComponents.beforeVariants(androidComponents.selector().withBuildType("release")) { it.enable = false }
// Separate disposable test app; it has no Sphere enrollment, VpnService or UI.
dependencies {
    implementation(project(":awg-sdk"))
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.kotlinx.serialization.json)
}

import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.ksp)
    alias(libs.plugins.hilt)
    alias(libs.plugins.kotlin.serialization)
}

// ── Version management ────────────────────────────────────────────────────
val versionProps = Properties()
val versionFile = rootProject.file("version.properties")
if (versionFile.exists()) versionProps.load(versionFile.inputStream())
val appVersionCode = versionProps.getProperty("VERSION_CODE", "10001").toInt()
val appVersionName: String = versionProps.getProperty("VERSION_NAME", "1.0.0")

// Build-specific URL takes precedence without modifying a shared installation's .env.
// Legacy fallback: sync-tunnel-url.sh updates SERVER_PUBLIC_URL in the root .env.
val dotEnvFile = rootProject.file("../.env")
val serverPublicUrl: String = System.getenv("SPHERE_SERVER_URL") ?: if (dotEnvFile.exists()) {
    dotEnvFile.readLines()
        .firstOrNull { it.startsWith("SERVER_PUBLIC_URL=") }
        ?.substringAfter("=")?.trim()?.removeSurrounding("\"")
        ?: "http://10.0.2.2:8000"
} else {
    "http://10.0.2.2:8000"
}

android {
    namespace = "com.sphereplatform.agent"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.sphereplatform.agent"
        minSdk = 26
        targetSdk = 35
        versionCode = appVersionCode
        versionName = appVersionName

        // Enterprise build metadata
        buildConfigField("String", "GIT_SHA", "\"${System.getenv("GIT_SHA") ?: "local"}\"")
        buildConfigField("String", "BUILD_TIME", "\"${System.currentTimeMillis()}\"")
        buildConfigField("String", "DEFAULT_FALLBACK_SERVER_URL", "\"${System.getenv("SPHERE_FALLBACK_SERVER_URL") ?: ""}\"")
    }

    // ── Signing (env-var driven, never commit keys to VCS) ───────────────────
    signingConfigs {
        create("release") {
            storeFile = System.getenv("SPHERE_KEYSTORE_PATH")?.let { file(it) }
            storePassword = System.getenv("SPHERE_KEYSTORE_PASSWORD") ?: ""
            keyAlias = System.getenv("SPHERE_KEY_ALIAS") ?: "sphere"
            keyPassword = System.getenv("SPHERE_KEY_PASSWORD") ?: ""
        }
    }

    // ── Build flavors ───────────────────────────────────────────────────
    flavorDimensions += "env"
    productFlavors {
        create("dev") {
            dimension = "env"
            // Separate pilot identity/storage from an already installed dev agent.
            applicationIdSuffix = System.getenv("SPHERE_DEV_APPLICATION_ID_SUFFIX") ?: ".dev"
            versionNameSuffix = "-dev"
            buildConfigField("boolean", "ALLOW_HTTP", "true")
            buildConfigField("String", "FLAVOR_LABEL", "\"dev\"")
            // Isolated dev builds can select their own server, enrollment and discovery.
            buildConfigField("String", "DEFAULT_SERVER_URL", "\"$serverPublicUrl\"")
            // Override with the key seeded into the selected development installation.
            buildConfigField("String", "DEFAULT_API_KEY", "\"${System.getenv("SPHERE_ENROLLMENT_KEY") ?: "sphr_dev_enrollment_key_2025"}\"")
            buildConfigField("String", "DEFAULT_DEVICE_ID", "\"\"")
            // A local SPHERE_CONFIG_URL avoids contacting the shared GitHub environment.
            // Legacy default: HTTP Config Endpoint через GitHub Raw.
            // БЕЗОПАСНОСТЬ: укажи pinned commit hash вместо mutable ветки `main`
            // для устранения supply-chain риска (зависимость от изменяемого ref).
            // Пример: https://raw.githubusercontent.com/RootOne1337/sphere-agent-config/<PINNED_COMMIT_HASH>/environments/development.json
            buildConfigField("String", "CONFIG_URL", "\"${System.getenv("SPHERE_CONFIG_URL") ?: "https://raw.githubusercontent.com/RootOne1337/sphere-agent-config/main/environments/development.json"}\"")
        }
        create("enterprise") {
            dimension = "env"
            buildConfigField("boolean", "ALLOW_HTTP", "false")
            buildConfigField("String", "FLAVOR_LABEL", "\"enterprise\"")
            // Enterprise: baked-in defaults are blank — provisioned via MDM or config file
            buildConfigField("String", "DEFAULT_SERVER_URL", "\"\"")
            buildConfigField("String", "DEFAULT_API_KEY", "\"\"")
            buildConfigField("String", "DEFAULT_DEVICE_ID", "\"\"")
            // TZ-12: HTTP Config Endpoint — задаётся при сборке через CI/CD
            buildConfigField("String", "CONFIG_URL", "\"${System.getenv("SPHERE_CONFIG_URL") ?: ""}\"")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            val rel = signingConfigs.findByName("release")
            if (rel?.storeFile?.exists() == true) signingConfig = rel
        }
        debug {
            isMinifyEnabled = false
            applicationIdSuffix = ".debug"
            buildConfigField("boolean", "VERBOSE_LOGGING", "true")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        buildConfig = true
    }
}

dependencies {
    // AndroidX
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.material)
    implementation(libs.androidx.activity.ktx)
    implementation(libs.androidx.lifecycle.runtime)

    // Splash Screen API
    implementation(libs.core.splashscreen)

    // Hilt DI
    implementation(libs.hilt.android)
    ksp(libs.hilt.compiler)

    // WorkManager + Hilt integration
    implementation(libs.work.runtime.ktx)
    implementation(libs.hilt.work)
    ksp(libs.hilt.work.compiler)

    // OkHttp WebSocket
    implementation(libs.okhttp)
    implementation(libs.okhttp.logging)

    // Kotlinx Serialization
    implementation(libs.kotlinx.serialization.json)

    // Coroutines
    implementation(libs.kotlinx.coroutines.android)

    // Encrypted SharedPreferences
    implementation(libs.security.crypto)

    // Logging
    implementation(libs.timber)

    // Lua Engine
    implementation(libs.luaj)

    // ── Testing ────────────────────────────────────────────────────────────
    testImplementation(libs.junit)
    testImplementation(libs.mockk)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.mockwebserver)
    testImplementation(libs.robolectric)
    testImplementation(libs.turbine)
}

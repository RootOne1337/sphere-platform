import groovy.json.JsonSlurper
import java.security.MessageDigest

// Same pinned AGP already loaded by the root application plugin.
plugins { id("com.android.library") }

fun digest(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

// Vendored source is reviewed/pinned, not downloaded during Gradle configuration.
val verifyUpstream by tasks.registering {
    inputs.file("upstream.lock.json")
    inputs.dir("src/main/java")
    inputs.file("COPYING")
    doLast {
        val lock = JsonSlurper().parse(file("upstream.lock.json")) as Map<*, *>
        val sources = lock["sources"] as Map<*, *>
        val expected = sources.keys.map { it.toString() }.toSet()
        val actual = fileTree("src/main/java").files.map { "tunnel/src/main/java/" + it.relativeTo(file("src/main/java")).invariantSeparatorsPath }.toSet() + "COPYING"
        require(expected == actual) { "AWG vendored source inventory differs from lock" }
        sources.forEach { (path, sha) ->
            val source = if (path == "COPYING") file("COPYING") else file("src/main/java/" + path.toString().removePrefix("tunnel/src/main/java/"))
            require(digest(source.readText(Charsets.UTF_8).replace("\r\n", "\n").toByteArray(Charsets.UTF_8)) == sha) { "AWG source fingerprint mismatch: $path" }
        }
    }
}

val nativeDirectory = providers.environmentVariable("SPHERE_AWG_NATIVE_DIR").orNull?.let { file(it).canonicalFile }
val verifyNative by tasks.registering {
    if (nativeDirectory != null) {
        inputs.file(nativeDirectory.resolve("manifest.json"))
        inputs.dir(nativeDirectory.resolve("jniLibs"))
    }
    doLast {
        require(nativeDirectory != null) { "SPHERE_AWG_NATIVE_DIR is required for native debug packaging" }
        val manifest = JsonSlurper().parse(nativeDirectory.resolve("manifest.json")) as Map<*, *>
        val upstream = JsonSlurper().parse(file("upstream.lock.json")) as Map<*, *>
        require(manifest["upstream_commit"] == upstream["commit"])
        require(manifest["runtime_sleep_clock_patch_applied"] == true) { "Android BOOTTIME overlay is required" }
        val nativeLock = JsonSlurper().parse(rootProject.file("awg-native.lock.json")) as Map<*, *>
        require(manifest["jni_lifecycle_hardened"] == true && manifest["jni_lifecycle_patch_sha256"] == nativeLock["android_jni_lifecycle_patch_sha256"]) { "Pinned JNI lifecycle patch is required" }
        require(manifest["diagnostic_only"] == true) { "Only explicit diagnostic native artifacts are supported by this module" }
        val artifacts = manifest["artifacts"] as List<*>
        require(artifacts.size == 3)
        require(artifacts.map { (it as Map<*, *>)["abi"] }.toSet() == setOf("x86_64", "arm64-v8a", "armeabi-v7a"))
        val expectedLibraries = artifacts.map { "${(it as Map<*, *>)["abi"]}/libwg-go.so" }.toSet()
        val actualLibraries = fileTree(nativeDirectory.resolve("jniLibs")) { include("**/*.so") }.files.map { it.relativeTo(nativeDirectory.resolve("jniLibs")).invariantSeparatorsPath }.toSet()
        require(actualLibraries == expectedLibraries) { "Unverified native library in AWG packaging directory" }
        artifacts.forEach {
            val row = it as Map<*, *>
            val library = nativeDirectory.resolve("jniLibs/${row["abi"]}/libwg-go.so").canonicalFile
            require(library.toPath().startsWith(nativeDirectory.toPath()))
            require(digest(library.readBytes()) == row["sha256"] && library.length() == (row["size"] as Number).toLong()) { "AWG native fingerprint mismatch" }
            require(row["jni_exports_verified"] == true && row["load_alignment_16k_verified"] == true)
        }
    }
}

android {
    namespace = "com.sphereplatform.awgsdk"
    compileSdk = 35
    defaultConfig { minSdk = 26; consumerProguardFiles("consumer-rules.pro") }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    // Never package a diagnostic library in a release AAR, even when configured.
    if (nativeDirectory != null) sourceSets.getByName("debug").jniLibs.srcDir(nativeDirectory.resolve("jniLibs"))
}
tasks.named("preBuild").configure { dependsOn(verifyUpstream) }
tasks.matching { it.name.startsWith("mergeDebugJniLibFolders") }.configureEach { if (nativeDirectory != null) dependsOn(verifyNative) }
dependencies {
    implementation("org.jetbrains.kotlin:kotlin-stdlib:${libs.versions.kotlin.get()}")
    implementation("androidx.annotation:annotation:1.8.0")
    compileOnly("com.google.code.findbugs:jsr305:3.0.2")
}

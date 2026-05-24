package com.ecomguide.network

import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory

object RetrofitClient {
    /** Base URL for both REST API and image assets.
     *  10.0.2.2 = Android emulator → host machine localhost.
     *  Change to your machine's LAN IP when testing on a real device. */
    const val BASE_URL = "http://10.0.2.2:8000/"

    val instance: Retrofit by lazy {
        Retrofit.Builder()
            .baseUrl(BASE_URL)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
    }

    val api: com.ecomguide.network.ApiService by lazy {
        instance.create(com.ecomguide.network.ApiService::class.java)
    }
}

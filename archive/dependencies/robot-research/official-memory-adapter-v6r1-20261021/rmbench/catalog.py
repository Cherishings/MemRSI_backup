"""Official task inventory. Task IDs are evaluator metadata, never policy observations."""
RMBENCH = ['observe_and_pickup','rearrange_blocks','put_back_block','swap_blocks',
           'swap_T','battery_try','blocks_ranking_try','cover_blocks','press_button']
REMEMBENCH = ['MemFruitInSinkLeftFar','MemFruitInSinkRightFar',
    'MemRetrieveOilsFromCounterLL','MemRetrieveOilsFromCounterLR',
    'MemRetrieveOilsFromCounterRL','MemRetrieveOilsFromCounterRR',
    'MemHeatPot','MemHeatPotMultiple','MemWashAndReturnLeft','MemWashAndReturnRight',
    'MemWashAndReturnSameLocation','MemPutKBreadInMicrowave','MemPutKBowlInCabinet']
TASKS={'rmbench':RMBENCH,'remembench':REMEMBENCH}
COMMITS={'RMBench':'7d1cdfc7661c273a7a5c5f6126e2d1a7f0a3f4b7',
 'ReMemBench':'f509073b0faced71a2d94f11714548ac507852cc',
 'robosuite-remem':'e1d9750f4732e2ab4e4bb0d4e80f9f09f6287dbb'}

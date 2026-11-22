class Branch {
  final String id;
  final String name;
  final String code;
  final String location;
  final bool isMain;

  const Branch({
    required this.id,
    required this.name,
    required this.code,
    required this.location,
    this.isMain = false,
  });

  factory Branch.fromJson(Map<String, dynamic> json) {
    return Branch(
      id: json['id']?.toString() ?? '',
      name: json['name']?.toString() ?? '',
      code: json['code']?.toString() ?? '',
      location: json['location']?.toString() ?? '',
      isMain: json['is_main'] == true,
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'code': code,
        'location': location,
        'is_main': isMain,
      };
}
